import React from "react";
import { Composition } from "remotion";
import { NessusPromo } from "./NessusPromo";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="NessusPromo"
      component={NessusPromo}
      durationInFrames={900}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
