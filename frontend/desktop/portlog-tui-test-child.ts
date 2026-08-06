process.stdout.write("TURN STARTED\n");
process.on("SIGTERM", () => {
  process.stdout.write("ASSISTANT: stale-after-dispose\n");
  setTimeout(() => process.exit(0), 10);
});
setInterval(() => {}, 1_000);
