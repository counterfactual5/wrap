import {Composition, registerRoot} from 'remotion';
import {Shot} from './Shot';
import type {ShotSpec} from './spec';

// The spec arrives as props (inline JSON or --props=./file), already validated
// by schema.py. One file drives S1 (prompt), S3 (this render) and S4 (gates).
// Props carry the spec content — not a path — so the bundle stays static.

export type ShotProps = {
  spec: ShotSpec;
  /** layer id -> data: URL of the S2-prepared PNG (AI assets and code backgrounds). */
  prepared: Record<string, string>;
  /** layer id -> absolute path of the S2-prepared mp4 (video layers). */
  preparedVideos?: Record<string, string>;
};

export const RemotionVideo: React.FC<ShotProps> = ({spec, prepared, preparedVideos}) => {
  return <Shot spec={spec} prepared={prepared} preparedVideos={preparedVideos} />;
};

export const Index: React.FC = () => {
  return (
    <>
      <Composition
        id="Shot"
        component={RemotionVideo}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={undefined as unknown as ShotProps}
        calculateMetadata={({props}) => ({
          durationInFrames: props.spec.durationInFrames,
          fps: props.spec.fps,
          width: props.spec.canvas.w,
          height: props.spec.canvas.h,
        })}
      />
    </>
  );
};

registerRoot(Index);
