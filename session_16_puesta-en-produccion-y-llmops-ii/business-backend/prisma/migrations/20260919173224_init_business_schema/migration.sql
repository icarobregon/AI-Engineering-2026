-- CreateTable
CREATE TABLE "estimations" (
    "id" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "project_type" TEXT NOT NULL,
    "detail_level" TEXT NOT NULL,
    "output_format" TEXT NOT NULL,
    "response_payload" JSONB NOT NULL,
    "prompt_version" TEXT NOT NULL,
    "cached" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "estimations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "supervisor_runs" (
    "id" TEXT NOT NULL,
    "estimation_id" TEXT NOT NULL,
    "transcript" TEXT NOT NULL,
    "run_state" TEXT NOT NULL DEFAULT 'running',
    "status" TEXT,
    "estimate" JSONB,
    "review_payload" JSONB,
    "human_decision" JSONB,
    "errors" JSONB NOT NULL DEFAULT '[]',
    "confidence" DOUBLE PRECISION,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "supervisor_runs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "estimations_created_at_idx" ON "estimations"("created_at");

-- CreateIndex
CREATE UNIQUE INDEX "supervisor_runs_estimation_id_key" ON "supervisor_runs"("estimation_id");

-- CreateIndex
CREATE INDEX "supervisor_runs_created_at_idx" ON "supervisor_runs"("created_at");

-- CreateIndex
CREATE INDEX "supervisor_runs_run_state_status_idx" ON "supervisor_runs"("run_state", "status");
