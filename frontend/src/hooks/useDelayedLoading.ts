import * as React from 'react';

/**
 * 遅延表示フック(hextaUI registry: use-delayed-loading)。
 *
 * 読み込みが速く終わる場合にスピナーを一瞬も出さない(delay)・
 * 表示したら最低表示時間を確保する(minDuration)ための 2 段の抑制。
 * 正規化: registry の `hooks/use-delayed-loading.ts` を本プロジェクトの
 * ファイル命名(camelCase)へ改名(docs/fe-floor-orientation-redesign-plan.md §6.4)。
 */

type DelayedLoadingOptions = {
  delay?: number;
  minDuration?: number;
};

function useDelayedLoading(
  loading: boolean,
  { delay = 150, minDuration = 400 }: DelayedLoadingOptions = {},
) {
  const [visible, setVisible] = React.useState(false);
  const shownAt = React.useRef(0);

  React.useEffect(() => {
    if (loading === visible) {
      return;
    }
    if (loading) {
      const timer = setTimeout(() => {
        shownAt.current = Date.now();
        setVisible(true);
      }, Math.max(0, delay));
      return () => clearTimeout(timer);
    }
    const remaining = Math.max(0, minDuration - (Date.now() - shownAt.current));
    const timer = setTimeout(() => setVisible(false), remaining);
    return () => clearTimeout(timer);
  }, [loading, visible, delay, minDuration]);

  return visible;
}

export { useDelayedLoading };
export type { DelayedLoadingOptions };
