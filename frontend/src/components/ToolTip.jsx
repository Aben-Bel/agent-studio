import React, { useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../i18n.jsx";

// Rich hover tooltip for a tool or skill: shows its name, what it CAN do
// (description) and what it CANNOT do (limits). Used everywhere a tool/skill is
// shown - the setup list, the inspect-agent modal, and the create-agent wizard.
//
// The card is rendered in a PORTAL on document.body and positioned with fixed
// coordinates next to the trigger. This is deliberate: the setup tools list is a
// scroll container (overflow:auto), which CLIPS any absolutely-positioned child
// no matter its z-index. A body portal is the only thing that reliably escapes
// every overflow/transform ancestor, so the tooltip is never hidden or cut off.
export default function ToolTip({ name, cap, cannot, children }) {
  const { t } = useI18n();
  const ref = useRef(null);
  const [pos, setPos] = useState(null);   // {top, left, placement} or null = hidden

  const show = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const W = 300, margin = 10;
    // Prefer above the trigger; flip below if there isn't room.
    const above = r.top > 160;
    let left = r.left;
    if (left + W + margin > window.innerWidth) left = window.innerWidth - W - margin;
    if (left < margin) left = margin;
    setPos({
      left,
      top: above ? r.top - margin : r.bottom + margin,
      placement: above ? "above" : "below",
    });
  }, []);

  const hide = useCallback(() => setPos(null), []);

  return (
    <span ref={ref} className="tt-wrap" tabIndex={0}
      onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {pos && createPortal(
        <span className={"tt-card tt-" + pos.placement} role="tooltip"
          style={{ top: pos.top, left: pos.left,
                   transform: pos.placement === "above" ? "translateY(-100%)" : "none" }}>
          {name && <span className="tt-name">{name}</span>}
          {cap && (
            <span className="tt-line tt-can">
              <span className="tt-mark">✓</span>
              <span><span className="tt-key">{t("ttCan")}</span> {cap}</span>
            </span>
          )}
          {cannot && (
            <span className="tt-line tt-cannot">
              <span className="tt-mark">✗</span>
              <span><span className="tt-key">{t("ttCannot")}</span> {cannot}</span>
            </span>
          )}
          {!cap && !cannot && <span className="tt-line tt-muted">{t("ttNone")}</span>}
        </span>,
        document.body)}
    </span>
  );
}
