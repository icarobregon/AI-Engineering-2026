-- CreateTable
CREATE TABLE "rag_runs" (
    "id" TEXT NOT NULL,
    "transcript" TEXT NOT NULL,
    "current_step" TEXT NOT NULL DEFAULT 'reformulation',
    "reformulation" JSONB,
    "structure" JSONB,
    "reviewed_modules" JSONB,
    "task_hours" JSONB,
    "verification" JSONB,
    "confirmed_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "rag_runs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "rag_runs_created_at_idx" ON "rag_runs"("created_at");

