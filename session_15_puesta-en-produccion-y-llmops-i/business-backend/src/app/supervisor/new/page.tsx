"use client";

import Link from "next/link";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Flex, Typography } from "antd";

import { TranscriptForm } from "./transcript-form";

export default function NewSupervisorRunPage() {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="baseline">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Nueva estimación supervisada
        </Typography.Title>
        <Link href="/supervisor">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Bandeja
          </Button>
        </Link>
      </Flex>
      <TranscriptForm />
    </Flex>
  );
}
