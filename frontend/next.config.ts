import { withAui } from "@assistant-ui/next";
import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default withAui(nextConfig);
