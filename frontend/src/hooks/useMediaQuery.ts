import { useEffect, useState } from 'react';

/**
 * matchMedia のリアクティブ判定。
 * CSS のブレークポイント切替と同じクエリ文字列を JS 側でも使う際の
 * 単一シグナルとして利用する(例: '(min-width: 640px)' = Tailwind sm)。
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const apply = () => setMatches(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [query]);
  return matches;
}
