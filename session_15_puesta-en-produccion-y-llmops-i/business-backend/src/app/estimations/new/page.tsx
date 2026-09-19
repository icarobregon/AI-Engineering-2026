"use client";

import Link from "next/link";
import { Flex, Typography } from "antd";

import { EstimationForm } from "./estimation-form";

export default function NewEstimationPage() {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="baseline">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Nueva estimación
        </Typography.Title>
        <Link href="/estimations">Ver histórico</Link>
      </Flex>
      <EstimationForm />
    </Flex>
  );
}
