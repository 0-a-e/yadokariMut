import React, { useCallback, useEffect, useState } from "react";
import {
  CopilotChat,
  useFrontendTool,
  ToolCallStatus,
  useAgent,
} from "@copilotkit/react-core/v2";
import { z } from "zod";
import "@copilotkit/react-core/v2/styles.css";
import { Skeleton } from "@/components/ui/skeleton.tsx";
import { Card, CardContent } from "@/components/ui/card.tsx";
import { EmptyState } from "@/components/shared/EmptyState.tsx";
import { LoadingState } from "@/components/shared/LoadingState.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import {
  FaFire,
  FaMapLocationDot,
  FaPlus,
  FaTrash,
  FaComments,
  FaClockRotateLeft,
  FaXmark,
  FaBuilding,
} from "react-icons/fa6";
import { createId } from "@/lib/utils.ts";
import { formatSessionTime } from "../../lib/format.ts";
// 比較行定義の正本(状態行は lib/shortlist.ts の fmtStatus でラベル変換される)
import { AGENT_COMPARISON_ROWS } from "../../lib/comparisonRows.ts";
import type { ChatSessionMeta } from "../../lib/chatSessions.ts";
import {
  deleteServerThread,
  fetchServerThreads,
  fetchThreadMessages,
  loadSessionMeta,
  mergeThreads,
  removeSessionMeta,
  setActiveThreadId,
  titleFromMessage,
  upsertSessionMeta,
} from "../../lib/chatSessions.ts";

interface AgentChatProps {
  threadId: string;
  onThreadChange: (threadId: string) => void;
  onSelectFeature: (id: number) => void;
  /** 建物選択(Phase B2-δ §4.6・App 側の暫定実装経由で部屋パネルを開く) */
  onSelectBuilding: (buildingId: number) => void;
}

export const AgentChat: React.FC<AgentChatProps> = ({
  threadId,
  onThreadChange,
  onSelectFeature,
  onSelectBuilding,
}) => {
  const { agent } = useAgent({ agentId: "yadokari_agent" });
  const [sessions, setSessions] = useState<ChatSessionMeta[]>(() => loadSessionMeta());
  const [showSessions, setShowSessions] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [hydrating, setHydrating] = useState(false);

  const refreshSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const server = await fetchServerThreads();
      const local = loadSessionMeta();
      // Ensure current thread is present
      const withCurrent = local.some((s) => s.id === threadId)
        ? local
        : [
            {
              id: threadId,
              title: "現在の会話",
              updatedAt: new Date().toISOString(),
            },
            ...local,
          ];
      setSessions(mergeThreads(server, withCurrent));
    } finally {
      setLoadingSessions(false);
    }
  }, [threadId]);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Hydrate messages when switching threads
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!agent) return;
      setHydrating(true);
      try {
        agent.threadId = threadId;
        const messages = await fetchThreadMessages(threadId);
        if (cancelled) return;
        if (messages.length > 0) {
          agent.setMessages(
            messages.map((m) => ({
              id: m.id,
              role: m.role as "user" | "assistant",
              content: m.content,
            })) as any,
          );
        } else {
          agent.setMessages([]);
        }
      } catch (e) {
        console.warn("Failed to hydrate thread messages", e);
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, agent]);

  // Track first user message to update session title
  useEffect(() => {
    if (!agent) return;
    const bump = () => {
      const msgs = agent.messages || [];
      const firstUser = msgs.find((m: any) => m.role === "user" && m.content);
      if (!firstUser) return;
      const content =
        typeof firstUser.content === "string"
          ? firstUser.content
          : String(firstUser.content ?? "");
      upsertSessionMeta({
        id: threadId,
        title: titleFromMessage(content),
        preview: content.slice(0, 80),
        updatedAt: new Date().toISOString(),
        messageCount: msgs.length,
      });
      // soft refresh list without loading spinner
      setSessions((prev) =>
        mergeThreads(
          prev.map((s) => ({ ...s })),
          loadSessionMeta(),
        ),
      );
    };
    bump();
    // AG-UI の購読APIでメッセージ変化を拾う(ポーリング不要)
    const subscription = agent.subscribe({ onMessagesChanged: bump });
    return () => subscription.unsubscribe();
  }, [agent, threadId]);

  const handleNewThread = () => {
    const id = createId();
    setActiveThreadId(id);
    upsertSessionMeta({
      id,
      title: "新しい会話",
      updatedAt: new Date().toISOString(),
      messageCount: 0,
    });
    onThreadChange(id);
    setShowSessions(false);
    refreshSessions();
  };

  const handleSelectSession = (id: string) => {
    if (id === threadId) {
      setShowSessions(false);
      return;
    }
    setActiveThreadId(id);
    onThreadChange(id);
    setShowSessions(false);
  };

  const handleDeleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm("この会話を削除しますか？サーバー上の履歴も消えます。")) return;
    await deleteServerThread(id);
    removeSessionMeta(id);
    if (id === threadId) {
      handleNewThread();
    } else {
      refreshSessions();
    }
  };

  useFrontendTool({
    name: "showProperties",
    description:
      "検索された物件の一覧をチャットUI上にきれいにカードやテーブルで表示する。物件をユーザーに提示する場合は、Markdownでテキスト出力する代わりに、必ずこのツールを呼ぶこと。",
    parameters: z.object({
      properties: z.array(
        z.object({
          id: z.number(),
          title: z.string(),
          rent: z.number(),
          layout: z.string(),
          area: z.number(),
          address: z.string(),
          score: z.number().optional(),
          station_walk: z.string().optional(),
        })
      ),
      title: z.string().optional(),
    }),
    handler: async (args) => {
      return `Displayed ${args.properties?.length ?? 0} properties in the chat.`;
    },
    render: ({ args, status }) => {
      if (
        status === ToolCallStatus.InProgress ||
        status === ToolCallStatus.Executing
      ) {
        return (
          <div className="flex flex-col gap-2 p-3 my-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
          </div>
        );
      }

      if (status === ToolCallStatus.Complete && args.properties) {
        return (
          <div className="flex flex-col gap-2 my-2 w-full">
            {args.title && (
              <h3 className="text-sm font-bold text-accent mb-1 flex items-center gap-1.5">
                <FaFire className="text-orange-500" /> {args.title}
              </h3>
            )}
            <div className="flex flex-col gap-2.5 max-h-[300px] overflow-y-auto pr-1 scrollbar-thin">
              {args.properties.map((prop) => (
                <Card key={prop.id} size="sm" className="hover:bg-white/[0.06] bg-black/25 border-border">
                  <CardContent className="p-3 flex flex-col gap-2">
                    <div className="flex justify-between items-start gap-2">
                      <span className="text-sm font-bold text-text line-clamp-1">{prop.title}</span>
                      <Badge
                        variant="outline"
                        className="text-xs shrink-0 border-primary/30 text-primary bg-primary/20"
                      >
                        ID: {prop.id}
                      </Badge>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-text-muted">
                      <div>
                        家賃:{" "}
                        <span className="text-text font-semibold">
                          {prop.rent?.toLocaleString() ?? "N/A"}円
                        </span>
                      </div>
                      <div>
                        間取り:{" "}
                        <span className="text-text font-semibold">
                          {prop.layout} ({prop.area}㎡)
                        </span>
                      </div>
                      {prop.station_walk && (
                        <div className="col-span-2">
                          アクセス: <span className="text-text">{prop.station_walk}</span>
                        </div>
                      )}
                      <div className="col-span-2">
                        住所: <span className="text-text line-clamp-1">{prop.address}</span>
                      </div>
                    </div>
                    <div className="flex justify-between items-center mt-1 pt-1.5 border-t border-white/5">
                      <span className="text-xs text-yellow-400 font-bold">
                        ★ {prop.score?.toFixed(2) ?? "N/A"}
                      </span>
                      <Button
                        variant="link"
                        size="xs"
                        className="text-accent hover:underline p-0 h-auto"
                        onClick={() => onSelectFeature(prop.id)}
                      >
                        <FaMapLocationDot className="mr-1" /> 地図で見る
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        );
      }
      return null;
    },
  }, [onSelectFeature]);

  useFrontendTool({
    name: "showComparison",
    description:
      "複数物件を表形式で比較表示する。compare_properties の結果や保存済み物件の比較時に必ず使う。" +
      "Markdown表の代わりにこのツールを呼ぶこと。期間総額は stayTotalYen、カタログ日額は catalogDailyYen または rent に載せる。",
    parameters: z.object({
      title: z.string().optional(),
      // フィールド名は ComparisonPropertyInput (lib/comparisonRows.ts) に合わせる
      properties: z.array(
        z.object({
          id: z.number(),
          title: z.string(),
          rent: z.number().optional(),
          catalogDailyYen: z.number().optional(),
          stayTotalYen: z.number().optional(),
          stayDays: z.number().optional(),
          layout: z.string().optional(),
          areaM2: z.number().optional(),
          floorNumber: z.number().nullable().optional(),
          floorNumberMax: z.number().nullable().optional(),
          orientationDeg: z.number().nullable().optional(),
          walkMinutes: z.number().nullable().optional(),
          score: z.number().optional(),
          address: z.string().optional(),
          featureSummary: z.string().optional(),
          shortlistStatus: z.string().optional(),
        })
      ),
    }),
    handler: async (args) => {
      return `Displayed comparison of ${args.properties?.length ?? 0} properties.`;
    },
    render: ({ args, status }) => {
      if (
        status === ToolCallStatus.InProgress ||
        status === ToolCallStatus.Executing
      ) {
        return (
          <div className="p-3 my-2">
            <Skeleton className="h-24 w-full" />
          </div>
        );
      }
      if (status !== ToolCallStatus.Complete || !args.properties?.length) return null;

      return (
        <div className="my-2 w-full overflow-x-auto rounded-lg bg-black/20 border border-border p-2">
          {args.title && (
            <h3 className="text-sm font-bold text-accent mb-2">{args.title}</h3>
          )}
          <table className="w-full text-xs border-collapse min-w-[360px]">
            <thead>
              <tr>
                <th className="text-left p-2 border-b border-border text-text-muted sticky left-0 bg-[#1a1c26]">
                  項目
                </th>
                {args.properties.map((p) => (
                  <th
                    key={p.id}
                    className="text-left p-2 border-b border-border text-text font-semibold max-w-[140px]"
                  >
                    <button
                      type="button"
                      className="text-accent hover:underline text-left"
                      onClick={() => onSelectFeature(p.id)}
                    >
                      {p.title || `ID ${p.id}`}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {AGENT_COMPARISON_ROWS.map((row) => (
                <tr key={row.key} className="border-b border-border/50">
                  <td className="p-2 text-text-muted sticky left-0 bg-[#1a1c26] font-medium">
                    {row.label}
                  </td>
                  {args.properties!.map((p) => (
                    <td key={p.id} className="p-2 text-text align-top max-w-[140px]">
                      {row.get(p)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    },
  }, [onSelectFeature]);

  // ── 建物一覧カード(Phase B2-δ §4.6・showProperties と同型) ──
  useFrontendTool({
    name: "showBuildings",
    description:
      "建物の一覧をチャットUI上にカードで表示する。建物単位でユーザーに提示する場合は、Markdownでテキスト出力する代わりに必ずこのツールを呼ぶこと。" +
      "部屋単位の一覧は showProperties を使う。rentBand は「4,800円〜7,500円/日」形式の帯表示文字列。",
    parameters: z.object({
      buildings: z.array(
        z.object({
          id: z.number(),
          name: z.string(),
          unitsCount: z.number().optional(),
          rentBand: z.string().optional(),
          minWalkMinutes: z.number().nullable().optional(),
        })
      ),
      title: z.string().optional(),
    }),
    handler: async (args) => {
      return `Displayed ${args.buildings?.length ?? 0} buildings in the chat.`;
    },
    render: ({ args, status }) => {
      if (
        status === ToolCallStatus.InProgress ||
        status === ToolCallStatus.Executing
      ) {
        return (
          <div className="flex flex-col gap-2 p-3 my-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
          </div>
        );
      }

      if (status === ToolCallStatus.Complete && args.buildings) {
        return (
          <div className="flex flex-col gap-2 my-2 w-full">
            {args.title && (
              <h3 className="text-sm font-bold text-accent mb-1 flex items-center gap-1.5">
                <FaBuilding className="text-orange-500" /> {args.title}
              </h3>
            )}
            <div className="flex flex-col gap-2.5 max-h-[300px] overflow-y-auto pr-1 scrollbar-thin">
              {args.buildings.map((b) => (
                <Card key={b.id} size="sm" className="hover:bg-white/[0.06] bg-black/25 border-border">
                  <CardContent className="p-3 flex flex-col gap-2">
                    <div className="flex justify-between items-start gap-2">
                      <span className="text-sm font-bold text-text line-clamp-1">{b.name}</span>
                      <Badge
                        variant="outline"
                        className="text-xs shrink-0 border-primary/30 text-primary bg-primary/20"
                      >
                        ID: {b.id}
                      </Badge>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-text-muted">
                      <div>
                        部屋数:{" "}
                        <span className="text-text font-semibold">
                          {b.unitsCount != null ? `${b.unitsCount}部屋` : "N/A"}
                        </span>
                      </div>
                      <div>
                        徒歩:{" "}
                        <span className="text-text font-semibold">
                          {b.minWalkMinutes != null ? `${b.minWalkMinutes}分` : "N/A"}
                        </span>
                      </div>
                      {b.rentBand && (
                        <div className="col-span-2">
                          最安帯: <span className="text-text">{b.rentBand}</span>
                        </div>
                      )}
                    </div>
                    <div className="flex justify-end items-center mt-1 pt-1.5 border-t border-white/5">
                      <Button
                        variant="link"
                        size="xs"
                        className="text-accent hover:underline p-0 h-auto"
                        onClick={() => onSelectBuilding(b.id)}
                      >
                        <FaMapLocationDot className="mr-1" /> 地図で見る
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        );
      }
      return null;
    },
  }, [onSelectBuilding]);

  const currentTitle =
    sessions.find((s) => s.id === threadId)?.title || `会話 ${threadId.slice(0, 8)}…`;

  return (
    <div className="h-full w-full flex flex-col overflow-hidden relative">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border shrink-0 bg-[#12141c]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Button
            type="button"
            variant={showSessions ? "default" : "outline"}
            size="xs"
            className="text-xs shrink-0"
            onClick={() => setShowSessions((v) => !v)}
            title="会話履歴"
          >
            <FaClockRotateLeft className="mr-1" />
            履歴
          </Button>
          <span className="text-xs text-text truncate" title={currentTitle}>
            {currentTitle}
          </span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="xs"
          className="text-xs text-text-muted hover:text-text shrink-0"
          onClick={handleNewThread}
        >
          <FaPlus className="mr-1" />
          新規
        </Button>
      </div>

      {/* Session list panel */}
      {showSessions && (
        <div className="absolute inset-x-0 top-[41px] bottom-0 z-20 flex flex-col bg-[#0f1118]/95 backdrop-blur-md border-b border-border">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-xs font-semibold text-text flex items-center gap-1.5">
              <FaComments className="text-primary" />
              過去の会話
            </span>
            <div className="flex gap-1">
              <Button
                type="button"
                variant="ghost"
                size="xs"
                className="text-xs text-text-muted"
                onClick={() => refreshSessions()}
                disabled={loadingSessions}
              >
                更新
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                className="text-text-muted"
                onClick={() => setShowSessions(false)}
              >
                <FaXmark />
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1.5">
            {loadingSessions && sessions.length === 0 && (
              <LoadingState className="text-xs p-3" />
            )}
            {!loadingSessions && sessions.length === 0 && (
              <EmptyState message="まだ会話がありません" className="text-xs p-3" />
            )}
            {sessions.map((s) => {
              const active = s.id === threadId;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => handleSelectSession(s.id)}
                  className={`group w-full text-left rounded-lg border px-3 py-2.5 transition-colors ${
                    active
                      ? "border-primary/50 bg-primary/15"
                      : "border-border bg-white/[0.03] hover:bg-white/[0.07] hover:border-white/15"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-text truncate">{s.title}</div>
                      {s.preview && (
                        <div className="text-[11px] text-text-muted line-clamp-2 mt-0.5">
                          {s.preview}
                        </div>
                      )}
                      <div className="text-[10px] text-text-muted mt-1">
                        {formatSessionTime(s.updatedAt)}
                        {s.messageCount != null ? ` · ${s.messageCount} メッセージ` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="shrink-0 p-1.5 rounded-md text-text-muted hover:text-danger hover:bg-danger/10 opacity-70 group-hover:opacity-100"
                      title="削除"
                      onClick={(e) => handleDeleteSession(s.id, e)}
                    >
                      <FaTrash className="text-xs" />
                    </button>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {hydrating && (
        <LoadingState
          label="履歴を読み込み中…"
          className="px-3 py-1 text-[10px] bg-black/30 border-b border-border"
        />
      )}

      <CopilotChat
        key={threadId}
        agentId="yadokari_agent"
        threadId={threadId}
        labels={{
          chatInputPlaceholder: "AIアシスタントに物件検索を依頼...",
          welcomeMessageText:
            "こんにちは！YadokariMutのAIアシスタントです。地図フィルターの操作、物件の検索・比較・ショートリスト保存ができます。例:「大阪で12万以下・1K・徒歩10分以内に絞って」",
        }}
        className="h-full w-full bg-transparent flex flex-col overflow-hidden flex-1 min-h-0 agent-chat-root"
        messageView={{
          className:
            "bg-transparent p-4 scrollbar-thin flex flex-col gap-3 overflow-y-auto flex-1",
          assistantMessage: {
            className:
              "agent-bubble-assistant text-text text-sm leading-[1.55] max-w-[92%] self-start flex flex-col gap-0.5 rounded-2xl rounded-bl-md border border-white/10 px-3.5 py-2.5 shadow-[0_4px_16px_rgba(0,0,0,0.35)]",
            copyButton: () => null,
            thumbsUpButton: () => null,
            thumbsDownButton: () => null,
            readAloudButton: () => null,
            regenerateButton: () => null,
            toolbar: () => null,
          },
          userMessage: {
            className:
              "agent-bubble-user text-white text-sm leading-[1.55] max-w-[92%] ml-auto flex flex-col gap-0.5 rounded-2xl rounded-br-md border border-primary/40 px-3.5 py-2.5 shadow-[0_4px_16px_rgba(133,77,255,0.25)]",
            copyButton: () => null,
            editButton: () => null,
            toolbar: () => null,
          },
          reasoningMessage: {
            className:
              "bg-black/35 border border-border/60 text-text-muted rounded-lg p-2 font-mono text-xs my-1 max-w-[92%]",
          },
        }}
        input={{
          className:
            "bg-[#12141c]/90 border-t border-border pt-3 pb-5 px-4 w-full shrink-0",
          disclaimer: () => null,
          textArea: {
            className:
              "bg-[#1a1c26] border border-border rounded-lg py-2.5 px-3.5 text-text text-base md:text-sm outline-hidden focus:border-primary/50 focus:bg-[#1e2030] placeholder:text-text-muted max-md:min-h-[44px]",
          },
          sendButton: {
            className:
              "w-[44px] h-[44px] max-md:w-[40px] max-md:h-[40px] rounded-lg border-none bg-primary text-white cursor-pointer flex items-center justify-center transition-all duration-200 hover:opacity-90 disabled:bg-white/[0.03] disabled:text-text-muted disabled:cursor-not-allowed",
          },
        }}
        welcomeScreen={false}
      />
    </div>
  );
};
