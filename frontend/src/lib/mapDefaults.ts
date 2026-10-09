/**
 * 既定地図ビューの正本。
 * MapPane(初期化) / App(zoom初期state) / useCopilotContext(AIコンテキストの
 * フォールバック中心) / useMapActions(fitBoundsパディング) に散在していた
 * 同値リテラルをここに集約する。
 */

/** アプリ初期表示の地図中心 [lat, lng](東京駅周辺)。useCopilotContext の例示文字列は除く */
export const DEFAULT_CENTER: [number, number] = [35.6812, 139.7671];

/** アプリ初期表示のズームレベル */
export const DEFAULT_ZOOM = 13;

/** fitBounds 時の画面端パディング(px)。初期フィットと AIツール(fitMapToFiltered)で共通 */
export const FIT_BOUNDS_PADDING: [number, number] = [50, 50];
