import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";
import type { ReadStatus } from "@/api/types";
import s from "./StatusPill.module.css";

const MENU_W = 160;
const MENU_H = 118;

export const READ_STATUS_LABEL: Record<ReadStatus, string> = {
  todo: "읽을 예정",
  reading: "읽는 중",
  done: "완료",
};

const ORDER: ReadStatus[] = ["todo", "reading", "done"];

interface Props {
  status: ReadStatus;
  /** 주면 드롭다운으로 바꿀 수 있어요. 없으면 표시만 해요 */
  onChange?: (status: ReadStatus) => void;
  size?: "sm" | "md" | "lg";
  /** 드롭다운 버튼의 스크린 리더 이름. "Attention Is All You Need 읽음 상태" */
  label?: string;
  className?: string;
}

/**
 * 읽음 상태 알약. 목업에서는 라이브러리(30px) · 리더(28px) · 모바일(11.5px)로
 * 크기만 달랐고 색과 드롭다운 마크업은 같았어요.
 */
export function StatusPill({
  status,
  onChange,
  size = "md",
  label,
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<CSSProperties>({});
  const wrap = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  // 메뉴는 페이지 맨 위층(body)에 띄워요 — 표처럼 넘치는 걸 자르는 틀 안에서도 다 보이게
  const place = () => {
    const r = wrap.current?.getBoundingClientRect();
    if (!r) return;
    const below = r.bottom + 4 + MENU_H <= window.innerHeight;
    setPos({
      position: "fixed",
      left: Math.max(8, Math.min(r.left, window.innerWidth - MENU_W - 8)),
      top: below ? r.bottom + 4 : Math.max(8, r.top - 4 - MENU_H),
    });
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!wrap.current?.contains(t) && !menu.current?.contains(t))
        setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    // 스크롤 · 크기 바뀜이면 닫아요 (버튼과 떨어져 떠 있지 않게)
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  const pill = (
    <span className={clsx(s.pill, s[size], s[status], className)}>
      {READ_STATUS_LABEL[status]}
    </span>
  );

  if (!onChange) return pill;

  return (
    <div ref={wrap} className={s.wrap}>
      <button
        type="button"
        data-interactive="true"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label ?? "읽음 상태 변경"}
        onClick={() => {
          if (!open) place();
          setOpen((v) => !v);
        }}
        className={clsx(s.pill, s[size], s[status], className)}
      >
        {READ_STATUS_LABEL[status]}
        <span aria-hidden="true" className={s.caret}>
          ▾
        </span>
      </button>

      {open &&
        createPortal(
          <div role="menu" ref={menu} className={s.menu} style={pos}>
            {ORDER.map((key) => (
              <button
                key={key}
                type="button"
                role="menuitemradio"
                aria-checked={key === status}
                onClick={() => {
                  onChange(key);
                  setOpen(false);
                }}
                className={s.item}
              >
                <span aria-hidden="true" className={s.mark}>
                  {key === status ? "✓" : ""}
                </span>
                {READ_STATUS_LABEL[key]}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
