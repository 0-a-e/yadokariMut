import { useCallback } from 'react';
import { getRouteApi, useNavigate } from '@tanstack/react-router';
import {
  applyExplorerSearchPatch,
  explorerSearchForNavigate,
  type ExplorerSearch,
  type ExplorerSearchPatch,
} from '../lib/explorerSearch';

const explorerRoute = getRouteApi('/');

export type PatchExplorerSearchOptions = {
  /**
   * true (default): replace current history entry (filters / dates / compare toggle).
   * false: push (property open / compare panel open).
   */
  replace?: boolean;
};

/**
 * Typed explorer search + patch helper for `/`.
 */
export function useExplorerSearch() {
  const search = explorerRoute.useSearch();
  const navigate = useNavigate({ from: '/' });

  const patchSearch = useCallback(
    (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => {
      const replace = opts?.replace ?? true;
      navigate({
        to: '/',
        search: (prev: ExplorerSearch) =>
          explorerSearchForNavigate(applyExplorerSearchPatch(prev, patch)) as ExplorerSearch,
        replace,
      });
    },
    [navigate],
  );

  const setSearch = useCallback(
    (next: ExplorerSearch, opts?: PatchExplorerSearchOptions) => {
      const replace = opts?.replace ?? true;
      navigate({
        to: '/',
        search: explorerSearchForNavigate(next) as ExplorerSearch,
        replace,
      });
    },
    [navigate],
  );

  return { search, patchSearch, setSearch };
}
