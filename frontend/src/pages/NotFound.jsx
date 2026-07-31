import React from "react";
import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div className="panel">
      <p className="empty">
        No such page.{" "}
        <Link className="linklike" to="/">back to the homepage</Link>
      </p>
    </div>
  );
}
