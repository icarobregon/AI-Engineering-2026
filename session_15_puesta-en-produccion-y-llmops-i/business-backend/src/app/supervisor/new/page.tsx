"use client";

import Link from "next/link";
import { Flex, Typography } from "antd";

import { TranscriptForm } from "./transcript-form";

export default function NewSupervisorRunPage() {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="baseline">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Nueva estimación supervisada
        </Typography.Title>
        <Link href="/supervisor">Ver bandeja</Link>
      </Flex>
      <TranscriptForm />
    </Flex>
  );
}
