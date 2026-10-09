/**
 * 「開発用: GeoJSON 読込」区画。ドラッグ&ドロップ / ファイル選択で
 * 建物 GeoJSON(/api/buildings/geojson 応答相当)を App の状態へ差し込む
 * (開発・デバッグ用)。成功/失敗は toast で通知する。
 */
import React, { useRef, useState } from 'react';
import { FaCloudArrowUp } from 'react-icons/fa6';
import { notify } from '../../lib/notify.ts';

export const GeoJsonUploadSection: React.FC<{
  onGeoJsonLoaded: (data: unknown) => void;
}> = ({ onGeoJsonLoaded }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const readGeoJsonFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        onGeoJsonLoaded(JSON.parse(evt.target?.result as string));
        notify('GeoJSON を読み込みました。');
      } catch {
        notify('JSONパースに失敗しました。正しいGeoJSONファイルを選択してください。', 'error');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div>
      <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
        開発用: GeoJSON 読込
      </h3>
      <div
        className="border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all duration-300 bg-white/[0.01] hover:border-primary hover:bg-primary/[0.05]"
        style={{
          borderColor: isDragOver ? 'var(--accent)' : 'rgba(133, 77, 255, 0.3)',
        }}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) readGeoJsonFile(file);
        }}
      >
        <FaCloudArrowUp className="text-2xl text-primary mb-2 inline-block" />
        <p className="text-sm text-text-muted">
          <b>建物 GeoJSON</b> をアップロード
        </p>
        <p className="text-xs text-text-muted mt-1">
          通常は API 経由で読み込みます（開発・デバッグ用）
        </p>
        <input
          type="file"
          ref={fileInputRef}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) readGeoJsonFile(file);
          }}
          accept=".geojson,application/json"
          hidden
        />
      </div>
    </div>
  );
};
