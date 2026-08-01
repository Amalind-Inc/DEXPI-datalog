module.exports = {
  appId: "org.portlog.desktop",
  productName: "PortLog",
  directories: {
    app: "release/electron-app",
    output: "release/dist",
  },
  files: ["**/*"],
  extraResources: [
    {
      from: "release/stage/ui",
      to: "ui",
    },
    {
      from: "release/stage/review-sidecar",
      to: "review-sidecar",
    },
    {
      from: "release/release-manifest.json",
      to: "release-manifest.json",
    },
  ],
  mac: {
    target: [
      { target: "dmg", arch: ["arm64"] },
      { target: "dir", arch: ["arm64"] },
    ],
    minimumSystemVersion: "14.0.0",
    category: "public.app-category.productivity",
    identity: "-",
    hardenedRuntime: false,
    strictVerify: false,
    signIgnore: "review-sidecar|Python\\.framework",
  },
};
