import React from "react";

/* v2 spec date group headings: plain Space Grotesk 21px lines, the
   relative prefix ("Today · ...") carrying the emphasis. Grouping
   logic (viewer-zone midnights, ordering policy) lives in daygroups
   and is unchanged. */
export const DaySep = ({ label, today }) => (
  <h2 className={"day-head" + (today ? " today" : "")}>{label}</h2>
);
export const DayRow = ({ label, span, today }) => (
  <tr className={"day-row" + (today ? " today" : "")}>
    <td colSpan={span}>{label}</td>
  </tr>
);
