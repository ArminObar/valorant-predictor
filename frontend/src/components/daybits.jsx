import React from "react";

export const DaySep = ({ label, today }) => (
  <div className={"day-sep" + (today ? " today" : "")}>
    <span>{label}</span>
  </div>
);


export const DayRow = ({ label, span, today }) => (
  <tr className={"day-row" + (today ? " today" : "")}>
    <td colSpan={span}>{label}</td>
  </tr>
);
