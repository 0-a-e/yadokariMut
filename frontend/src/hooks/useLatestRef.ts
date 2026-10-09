import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

/**
 * 値を常に最新に保つref。
 * CopilotKit useFrontendTool の handler(effect依存外のため addTool 時の
 * クロージャが永続使用される)や Leaflet リスナーなど、React の再レンダー外から
 * 呼ばれるコールバックで古い props/state を読まないための共通パターン。
 * (useMapActions / MapPane で「useRef + 最新化 useEffect」が重複していたのを解消)
 */
export function useLatestRef<T>(value: T): RefObject<T> {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref;
}
