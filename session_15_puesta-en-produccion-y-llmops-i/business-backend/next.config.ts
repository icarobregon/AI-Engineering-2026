import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle so the runtime image does not need
  // node_modules — the difference between a 1.5 GB image and a ~200 MB one.
  output: "standalone",
  // antd ships its components as ESM; transpiling keeps the server build happy.
  transpilePackages: ["antd", "@ant-design/icons", "@ant-design/cssinjs"],
  // Next writes its own AGENTS.md/CLAUDE.md into the app folder. The session
  // already has a CLAUDE.md one level up and a second one here would shadow it.
  agentRules: false,
};

export default nextConfig;
