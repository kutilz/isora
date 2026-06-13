import type { JSX, ComponentChildren } from "preact";
import { useManifests, hasAsset } from "../../lib/manifests";

/**
 * AssetImage — renders <img src="/assets/{name}"> if the file is listed
 * in /assets/manifest.json, otherwise falls back to the SVG mockup
 * passed as `fallback`. Pattern from handoff §8.6.
 */
export interface AssetImageProps {
  name: string;
  alt: string;
  fallback: ComponentChildren;
  className?: string;
  style?: JSX.CSSProperties;
}

export function AssetImage({
  name,
  alt,
  fallback,
  className,
  style,
}: AssetImageProps): JSX.Element {
  const m = useManifests();
  if (hasAsset(m, name)) {
    return (
      <img
        src={`/assets/${name}`}
        alt={alt}
        className={className}
        style={style}
      />
    );
  }
  return <>{fallback}</> as unknown as JSX.Element;
}
