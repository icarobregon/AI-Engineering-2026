"use client";

import { useState } from "react";
import { Form, Select } from "antd";

/**
 * An antd Select that reaches FormData.
 *
 * antd renders a div, not a native <select>, so a plain `name` never shows up in
 * the submitted form. The hidden input is the bridge — cheaper than wiring the
 * whole page through antd's Form instance just to call a server action.
 */
export function SelectField<T extends string>({
  name,
  label,
  defaultValue,
  options,
  width = 200,
}: {
  name: string;
  label: string;
  defaultValue: T;
  options: { value: T; label: string }[];
  width?: number;
}) {
  const [value, setValue] = useState<T>(defaultValue);

  return (
    <Form.Item label={label} layout="vertical" style={{ marginBottom: 0 }}>
      <input type="hidden" name={name} value={value} />
      <Select<T> value={value} onChange={setValue} options={options} style={{ width }} />
    </Form.Item>
  );
}
