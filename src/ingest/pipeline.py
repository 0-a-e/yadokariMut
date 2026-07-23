"""Ingest pipeline: list → detail → repository (per ListTarget)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ingest.raw_store import save_raw_page
from sources.base import ListCard, ListTarget, SourceAdapter
from store.repository import Repository

logger = logging.getLogger(__name__)


@dataclass
class TargetIngestResult:
    """Per-prefecture (ListTarget) ingest outcome."""

    target_key: str
    prefecture_slug: str | None = None
    list_pages: int = 0
    list_items: int = 0
    detail_ok: int = 0
    detail_fail: int = 0
    seen_external_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    list_completed: bool = False
    status: str = "ok"


@dataclass
class IngestResult:
    source_site: str
    list_pages: int = 0
    list_items: int = 0
    detail_ok: int = 0
    detail_fail: int = 0
    upserted_ids: list[int] = field(default_factory=list)
    seen_external_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    transfer: dict | None = None
    by_target: dict[str, TargetIngestResult] = field(default_factory=dict)


class IngestPipeline:
    def __init__(
        self,
        adapter: SourceAdapter,
        repo: Repository,
        *,
        save_raw: bool = True,
    ):
        self.adapter = adapter
        self.repo = repo
        self.save_raw = save_raw

    def run(
        self,
        *,
        max_pages: int | None = None,
        list_only: bool = False,
        max_details: int | None = None,
        skip_existing_detail_days: int | None = None,
        mark_inactive: bool = False,
    ) -> IngestResult:
        result = IngestResult(source_site=self.adapter.source_id)
        from sources.http.metrics import get_transfer_metrics

        metrics = get_transfer_metrics()
        targets = self.adapter.discover_list_targets()
        pref_keys = [t.prefecture_slug or t.key for t in targets]

        run_id = self.repo.start_scrape_run(
            self.adapter.source_id,
            meta={
                "max_pages": max_pages,
                "list_only": list_only,
                "max_details": max_details,
                "mark_inactive": mark_inactive,
                "prefs": pref_keys,
            },
        )

        details_remaining = max_details
        try:
            for target in targets:
                self._run_target(
                    target,
                    result,
                    run_id=run_id,
                    max_pages=max_pages,
                    list_only=list_only,
                    details_remaining=details_remaining,
                    mark_inactive=mark_inactive,
                )
                tr = result.by_target.get(target.prefecture_slug or target.key)
                if tr and details_remaining is not None:
                    details_remaining = max(0, details_remaining - tr.detail_ok - tr.detail_fail)

            snap = metrics.snapshot()
            src_stats = (snap.get("lifetime") or {}).get("by_source", {}).get(
                self.adapter.source_id
            )
            result.transfer = src_stats

            self.repo.finish_scrape_run(
                run_id,
                status="ok" if not result.errors else "partial",
                list_pages=result.list_pages,
                list_items=result.list_items,
                detail_ok=result.detail_ok,
                detail_fail=result.detail_fail,
                error_summary="; ".join(result.errors[:5]) if result.errors else None,
            )
        except Exception as e:
            logger.exception("Ingest failed")
            result.errors.append(str(e))
            self.repo.finish_scrape_run(
                run_id,
                status="error",
                list_pages=result.list_pages,
                list_items=result.list_items,
                detail_ok=result.detail_ok,
                detail_fail=result.detail_fail,
                error_summary=str(e),
            )
            raise

        return result

    def _run_target(
        self,
        target: ListTarget,
        result: IngestResult,
        *,
        run_id: int,
        max_pages: int | None,
        list_only: bool,
        details_remaining: int | None,
        mark_inactive: bool,
    ) -> None:
        target_key = target.prefecture_slug or target.key
        tr = TargetIngestResult(
            target_key=target_key,
            prefecture_slug=target.prefecture_slug,
        )
        result.by_target[target_key] = tr

        target_run_id = self.repo.start_scrape_run_target(
            run_id,
            self.adapter.source_id,
            target_key,
        )

        try:
            cards = self._collect_list_cards_for_target(
                target, result, tr, max_pages=max_pages
            )
            tr.list_completed = True
            tr.list_items = len(cards)
            tr.seen_external_ids = {c.external_id for c in cards}
            result.list_items += tr.list_items
            result.seen_external_ids |= tr.seen_external_ids

            if not list_only:
                self._scrape_details(
                    cards,
                    result,
                    tr,
                    max_details=details_remaining,
                )

            if mark_inactive and tr.list_completed:
                slug = target.prefecture_slug
                if slug:
                    n = self.repo.mark_inactive_missing(
                        self.adapter.source_id,
                        tr.seen_external_ids,
                        prefecture_slug=slug,
                    )
                    logger.info(
                        "Marked inactive for %s/%s: %s",
                        self.adapter.source_id,
                        slug,
                        n,
                    )
                else:
                    logger.warning(
                        "Skip mark_inactive for target %s: no prefecture_slug "
                        "(refusing source-wide sweep)",
                        target_key,
                    )

            tr.status = "ok" if not tr.errors else "partial"
            self.repo.finish_scrape_run_target(
                target_run_id,
                status=tr.status,
                list_pages=tr.list_pages,
                list_items=tr.list_items,
                detail_ok=tr.detail_ok,
                detail_fail=tr.detail_fail,
                error_summary="; ".join(tr.errors[:3]) if tr.errors else None,
            )
        except Exception as e:
            logger.exception("Target ingest failed: %s", target_key)
            tr.errors.append(str(e))
            tr.status = "error"
            result.errors.append(f"{target_key}: {e}")
            self.repo.finish_scrape_run_target(
                target_run_id,
                status="error",
                list_pages=tr.list_pages,
                list_items=tr.list_items,
                detail_ok=tr.detail_ok,
                detail_fail=tr.detail_fail,
                error_summary=str(e),
            )
            # Continue other targets rather than aborting the whole source run
            return

    def ingest_detail_html(
        self,
        html: str,
        *,
        detail_url: str = "",
        external_id: str = "",
        prefecture_slug: str | None = None,
        prefecture_name: str | None = None,
    ) -> int:
        """Offline / fixture path: parse detail HTML and upsert."""
        from sources.base import FetchedPage, ListCard

        card = ListCard(
            external_id=external_id or "unknown",
            detail_url=detail_url,
            prefecture_slug=prefecture_slug,
            prefecture_name=prefecture_name,
        )
        page = FetchedPage(url=detail_url, html=html, status_code=200, page_type="detail")
        draft = self.adapter.parse_detail(page, card)
        if external_id and draft.external_id in ("unknown", ""):
            draft.external_id = external_id
        path = None
        if self.save_raw:
            path = save_raw_page(page, source_site=self.adapter.source_id, repo=self.repo)
            draft.raw_html_path = path
        return self.repo.upsert_property(draft)

    def _collect_list_cards_for_target(
        self,
        target: ListTarget,
        result: IngestResult,
        tr: TargetIngestResult,
        *,
        max_pages: int | None,
    ) -> list[ListCard]:
        by_id: dict[str, ListCard] = {}
        page_size = self.adapter.page_size()
        page_no = 1
        total: int | None = None

        while True:
            if max_pages is not None and page_no > max_pages:
                break
            try:
                fetched = self.adapter.fetch_list_page(target, page_no)
            except Exception as e:
                msg = f"list {target.key} p{page_no}: {e}"
                logger.error(msg)
                result.errors.append(msg)
                tr.errors.append(msg)
                raise

            if self.save_raw:
                save_raw_page(fetched, source_site=self.adapter.source_id, repo=self.repo)

            result.list_pages += 1
            tr.list_pages += 1
            if total is None:
                total = self.adapter.list_total_count(fetched)

            cards = self.adapter.parse_list(fetched, target)
            if not cards:
                logger.info("No cards on %s page %s — stop", target.key, page_no)
                break

            for c in cards:
                by_id[c.external_id] = c

            has_next_flag = None
            if cards and isinstance(cards[0].raw, dict) and "_has_next" in cards[0].raw:
                has_next_flag = bool(cards[0].raw.get("_has_next"))

            if total is not None and page_no * page_size >= total:
                break
            if has_next_flag is False:
                break
            if has_next_flag is None and len(cards) < page_size:
                break
            page_no += 1

        return list(by_id.values())

    def _scrape_details(
        self,
        cards: list[ListCard],
        result: IngestResult,
        tr: TargetIngestResult,
        *,
        max_details: int | None,
    ) -> None:
        for i, card in enumerate(cards):
            if max_details is not None and i >= max_details:
                break
            try:
                fetched = self.adapter.fetch_detail_page(card)
                if self.save_raw:
                    path = save_raw_page(
                        fetched, source_site=self.adapter.source_id, repo=self.repo
                    )
                else:
                    path = None
                draft = self.adapter.parse_detail(fetched, card)
                draft.raw_html_path = path
                pid = self.repo.upsert_property(draft)
                result.upserted_ids.append(pid)
                result.detail_ok += 1
                tr.detail_ok += 1
            except Exception as e:
                result.detail_fail += 1
                tr.detail_fail += 1
                msg = f"detail {card.external_id}: {e}"
                logger.warning(msg)
                result.errors.append(msg)
                tr.errors.append(msg)
