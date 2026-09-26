"use client";

import Link from "next/link";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Flex, Typography } from "antd";

import { EstimationForm } from "./estimation-form";

export default function NewEstimationPage() {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="baseline">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Nueva estimación
        </Typography.Title>
        <Link href="/estimations">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Histórico
          </Button>
        </Link>
      </Flex>
      <EstimationForm />
    </Flex>
  );
}
