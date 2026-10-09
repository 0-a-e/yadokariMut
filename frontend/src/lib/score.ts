/**
 * 物件スコアの表示色。しきい値はカードバッジ・マップピンで共通の規約。
 * (旧 PropertyCard から移設。MapPane のピン描画からも利用する)
 *
 * 返値の使用先は全て DOM inline style(PropertyCard の Badge background /
 * MapPane の divIcon HTML background-color)であり、Canvas 描画には渡されない
 * ため var(--color-*) 参照が有効。Canvas へ渡す箇所を追加する場合は
 * getComputedStyle で解決した hex を渡すこと(CSS 変数は Canvas で効かない)。
 *
 * スコア帯 60(シアン)のみ #00f2fe を hex 維持している:
 * --color-accent は var(--accent) = oklch(0.85 0.20 200) に解決され、
 * #00f2fe と同値でないため(index.css @theme 参照)。TODO: 同値のテーマ変数が
 * 追加されたら var() 参照へ寄せる。
 */
export function getScoreColor(score: number): string {
  if (!score) return 'var(--color-text-muted)';
  if (score >= 80) return 'var(--color-success)';
  if (score >= 60) return '#00f2fe';
  if (score >= 40) return 'var(--color-warning)';
  return 'var(--color-danger)';
}
