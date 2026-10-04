/**
 * 物件スコアの表示色。しきい値はカードバッジ・マップピンで共通の規約。
 * (旧 PropertyCard から移設。MapPane のピン描画からも利用する)
 */
export function getScoreColor(score: number): string {
  if (!score) return '#8e95a5';
  if (score >= 80) return '#00e676';
  if (score >= 60) return '#00f2fe';
  if (score >= 40) return '#ffb300';
  return '#ff1744';
}
