import { ReactNode } from "react";
import { EmptyState } from "@/components/ui/async-state";

export type TableColumn<Row> = {
  key: string;
  label: string;
  render: (row: Row) => ReactNode;
  align?: "start" | "center" | "end";
};

export function ResponsiveDataTable<Row>({ caption, rows, columns, getRowKey, emptyTitle = "אין פריטים להצגה", emptyDescription }: {
  caption: string;
  rows: readonly Row[];
  columns: readonly TableColumn<Row>[];
  getRowKey: (row: Row) => string | number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (rows.length === 0) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return <div className="table-scroll" role="region" aria-label={caption} tabIndex={0}><table className="responsive-data-table"><caption>{caption}</caption><thead><tr>{columns.map((column) => <th key={column.key} scope="col" className={`align-${column.align ?? "start"}`}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={getRowKey(row)}>{columns.map((column) => <td key={column.key} data-label={column.label} className={`align-${column.align ?? "start"}`}>{column.render(row)}</td>)}</tr>)}</tbody></table></div>;
}
