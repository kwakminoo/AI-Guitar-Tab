"use client";

import React from "react";
import {
  ALPHATAB_BEAT_MODEL,
  ALPHATAB_NOTE_MODEL,
  ALPHATAB_PIPELINE,
  ALPHATAB_SCORE_HIERARCHY,
} from "@/data/alphatabModelReference";

function ListBlock({
  title,
  rows,
}: {
  title: string;
  rows: { ko: string; en?: string; api?: string }[];
}) {
  return (
    <section className="border-b border-zinc-100 pb-3 last:border-0">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
        {title}
      </h3>
      <ul className="space-y-1.5 text-[11px] leading-snug text-zinc-700">
        {rows.map((row) => (
          <li key={`${row.ko}-${row.en ?? row.api}`}>
            <span className="text-zinc-900">{row.ko}</span>
            {(row.en ?? row.api) && (
              <span className="ml-1 font-mono text-[10px] text-zinc-500">
                {row.en ?? row.api}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export const NodeSection: React.FC = () => {
  return (
    <div className="flex h-full min-h-[420px] w-full flex-col rounded-xl border border-zinc-200 bg-white shadow-sm md:w-80">
      <div className="border-b border-zinc-100 px-4 py-2">
        <span className="text-sm font-semibold text-zinc-900">노드 섹션</span>
        <p className="mt-1 text-[11px] leading-snug text-zinc-500">
          alphaTab 런타임 모델·프로퍼티 참조 (@coderline/alphatab 1.8.x, 공식 문서·타입
          정의 기준). 개별 “도형 SVG” 파일은 배포되지 않으며, 렌더러가 모델에서 글리프를
          생성합니다.
        </p>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        <ListBlock title="문서: 데이터 모델 계층" rows={ALPHATAB_SCORE_HIERARCHY} />
        <ListBlock
          title="문서·Note 클래스: 효과/표기 (발췌)"
          rows={ALPHATAB_NOTE_MODEL}
        />
        <ListBlock title="Beat 클래스: 박 단위 효과 (발췌)" rows={ALPHATAB_BEAT_MODEL} />
        <ListBlock title="파이프라인" rows={ALPHATAB_PIPELINE} />
        <p className="text-[10px] leading-relaxed text-zinc-400">
          전체 속성은 <code className="rounded bg-zinc-100 px-1">node_modules/@coderline/alphatab/dist/alphaTab.d.ts</code>{" "}
          의 <code className="rounded bg-zinc-100 px-1">Note</code>,{" "}
          <code className="rounded bg-zinc-100 px-1">Beat</code> 선언을 참고하세요.
        </p>
      </div>
    </div>
  );
}
