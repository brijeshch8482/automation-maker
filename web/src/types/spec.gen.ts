/* Generated from spec/schema/automation_spec.schema.json by `npm run gen:types`. Do not edit. */

/**
 * One automation. Source of truth for the web preview, EXE, tests and guide.
 */
export interface AutomationSpec {
  id: string;
  version: string;
  title: string;
  description?: string;
  category: "documents" | "pdf" | "images" | "excel" | "files" | "convert" | "other";
  network?: Network;
  settings?: (
    | TextField
    | NumberField
    | MoneyField
    | PhoneField
    | EmailField
    | DateField
    | FileField
    | FilesField
    | FolderField
    | ImageFileField
    | SelectField
    | CheckboxField
    | TableField
  )[];
  inputs?: (
    | TextField
    | NumberField
    | MoneyField
    | PhoneField
    | EmailField
    | DateField
    | FileField
    | FilesField
    | FolderField
    | ImageFileField
    | SelectField
    | CheckboxField
    | TableField
  )[];
  /**
   * @minItems 1
   */
  steps: [Step, ...Step[]];
  output: Output;
  sample_data?: {
    [k: string]: unknown;
  };
}
export interface Network {
  required?: boolean;
  domains?: string[];
}
export interface TextField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "text";
  multiline?: boolean;
  default?: string | null;
}
export interface NumberField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "number";
  min?: number | null;
  max?: number | null;
  default?: number | null;
}
export interface MoneyField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "money";
  currency?: string;
  default?: number | null;
}
export interface PhoneField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "phone";
  default?: string | null;
}
export interface EmailField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "email";
  default?: string | null;
}
export interface DateField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "date";
  default?: "today" | null;
}
export interface FileField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  extensions?: string[];
  type: "file";
}
export interface FilesField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  extensions?: string[];
  type: "files";
  min_count?: number;
}
export interface FolderField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "folder";
}
export interface ImageFileField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "image_file";
}
export interface SelectField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "select";
  /**
   * @minItems 1
   */
  options: [string, ...string[]];
  default?: string | null;
}
export interface CheckboxField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "checkbox";
  default?: boolean;
}
export interface TableField {
  key: string;
  label?: string | null;
  required?: boolean;
  help?: string | null;
  type: "table";
  /**
   * @minItems 1
   */
  columns: [
    (
      | TextField
      | NumberField
      | MoneyField
      | PhoneField
      | EmailField
      | DateField
      | SelectField
      | CheckboxField
    ),
    ...(
      | TextField
      | NumberField
      | MoneyField
      | PhoneField
      | EmailField
      | DateField
      | SelectField
      | CheckboxField
    )[]
  ];
  min_rows?: number;
}
export interface Step {
  block: string;
  args?: {
    [k: string]: unknown;
  };
  out?: string | null;
}
export interface Output {
  type: "file" | "files" | "folder" | "none";
  open_after?: boolean;
}
