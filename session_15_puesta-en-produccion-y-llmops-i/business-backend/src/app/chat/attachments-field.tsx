"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Form, Upload, type UploadFile } from "antd";
import { UploadOutlined } from "@ant-design/icons";

/**
 * An antd Upload that reaches FormData.
 *
 * Same problem as `SelectField`, one turn harder: a hidden text input cannot
 * carry a File. The bridge is a hidden `<input type="file">` whose `files` are
 * rebuilt from the Upload's list through a `DataTransfer` — the only way to
 * write a FileList by hand — so the server action keeps reading
 * `formData.getAll("attachments")` and knows nothing about any of this.
 *
 * `beforeUpload` returns false on purpose: without it antd would POST each file
 * to its own `action` endpoint, which does not exist here. The files travel with
 * the turn or not at all.
 */
export function AttachmentsField({ clearOn }: { clearOn: unknown }) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const bridge = new DataTransfer();
    for (const item of fileList) {
      if (item.originFileObj) bridge.items.add(item.originFileObj);
    }
    input.files = bridge.files;
  }, [fileList]);

  // Adjuntos are per-turn: their text is folded into the transcript before
  // estimating, so keeping them listed after a turn lands would re-send them on
  // the next one. Only a result clears them — an error leaves the selection
  // alone so the retry does not start from scratch.
  useEffect(() => {
    if (clearOn) setFileList([]);
  }, [clearOn]);

  return (
    <Form.Item
      label="Adjuntos"
      layout="vertical"
      extra="PDF y DOCX. Su texto se añade al turno antes de estimar."
      style={{ marginBottom: 0 }}
    >
      <input ref={inputRef} type="file" name="attachments" multiple hidden />
      <Upload
        multiple
        accept=".pdf,.docx"
        fileList={fileList}
        beforeUpload={() => false}
        onChange={({ fileList: next }) => setFileList(next)}
      >
        <Button icon={<UploadOutlined />}>Elegir archivos</Button>
      </Upload>
    </Form.Item>
  );
}
