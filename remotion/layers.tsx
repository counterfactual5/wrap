// The bar layer: a solid-color CSS div. The grid/dots backgrounds are NOT
// re-implemented here — S2 renders them to PNG (lib/draw.py) and they flow
// through as prepared assets, so pixels stay identical and there is exactly
// one implementation of every code layer.

export const Bar: React.FC<{color: string; width: number; height: number}> = ({
  color,
  width,
  height,
}) => (
  <div
    style={{
      position: 'absolute',
      width,
      height,
      backgroundColor: color,
    }}
  />
);
