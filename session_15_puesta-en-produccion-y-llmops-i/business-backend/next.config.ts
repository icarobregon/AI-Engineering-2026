import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle so the runtime image does not need
  // node_modules — the difference between a 1.5 GB image and a ~200 MB one.
  output: "standalone",
  // antd ships its components as ESM; transpiling keeps the server build happy.
  transpilePackages: ["antd", "@ant-design/icons", "@ant-design/cssinjs"],
  // pdfkit reads its font metrics (`js/data/*.afm`) from disk at run time.
  // Bundling it would rewrite those reads against paths that do not exist in the
  // standalone output, and the PDF route would die on its first request with an
  // ENOENT for Helvetica.afm.
  serverExternalPackages: ["pdfkit"],
  // ...and keeping it external is only half of it: the tracer follows `import`s,
  // not `fs.readFileSync`, so the .afm files have to be named explicitly or they
  // never reach the image. Verified by building and listing the standalone tree.
  outputFileTracingIncludes: {
    "/supervisor/[id]/proposal.pdf": ["./node_modules/**/pdfkit/js/data/*.afm"],
  },
  // Next writes its own AGENTS.md/CLAUDE.md into the app folder. The session
  // already has a CLAUDE.md one level up and a second one here would shadow it.
  agentRules: false,
};

export default nextConfig;
