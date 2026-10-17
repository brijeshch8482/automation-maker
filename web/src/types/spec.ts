import type { AutomationSpec, TableField } from "./spec.gen";

export type * from "./spec.gen";

/** Any field allowed in settings or inputs. */
export type SpecField = NonNullable<AutomationSpec["inputs"]>[number];
/** Any field allowed as a table column. */
export type ColumnField = TableField["columns"][number];
export type Category = AutomationSpec["category"];
