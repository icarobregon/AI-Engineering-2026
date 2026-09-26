-- CreateTable
CREATE TABLE "index_runs" (
    "id" TEXT NOT NULL,
    "chunk_type" TEXT NOT NULL,
    "documents_json" TEXT NOT NULL,
    "submitted_count" INTEGER NOT NULL,
    "processed_count" INTEGER NOT NULL DEFAULT 0,
    "skipped_count" INTEGER NOT NULL DEFAULT 0,
    "chunks_created" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "error_message" TEXT,
    "before_stats" JSONB,
    "after_stats" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "index_runs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "index_runs_created_at_idx" ON "index_runs"("created_at");

