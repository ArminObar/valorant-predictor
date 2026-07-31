import React from "react";

export function Mark({ size = 17 }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      <rect x="1" y="7" width="11" height="6" rx="1.5" fill="var(--a)" />
      <rect x="13.6" y="7" width="5.4" height="6" rx="1.5" fill="var(--b)" />
    </svg>
  );
}
