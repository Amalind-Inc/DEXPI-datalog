import Image from "next/image";

export function HarborfieldMark({
  className,
  priority = false,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src="/harborfield-sailboat.svg"
      alt="Harborfield sailboat"
      width={64}
      height={64}
      className={className}
      priority={priority}
    />
  );
}
