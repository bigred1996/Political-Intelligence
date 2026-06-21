import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { C } from "./style";
import {
  AskNessusGfx,
  CloseFast,
  ConnectionWeb,
  EntityMerge,
  IntroFast,
  ProofFlash,
  RiskBars,
  SourcesUnify,
  StatSlam,
} from "./graphics";

/* Fast, beat-synced timeline. 150 BPM => 12 frames/beat; cuts land on beats.
   Hard cuts (no crossfade) for a snappy, graphics-forward pace. */
const Cut: React.FC<{ from: number; dur: number; children: React.ReactNode }> = ({ from, dur, children }) => (
  <Sequence from={from} durationInFrames={dur} layout="none">
    {children}
  </Sequence>
);

export const NessusPromo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: C.navy }}>
      <Audio src={staticFile("music.wav")} />

      <Cut from={0} dur={96}><IntroFast /></Cut>
      <Cut from={96} dur={144}><StatSlam /></Cut>
      <Cut from={240} dur={96}><SourcesUnify /></Cut>
      <Cut from={336} dur={120}><EntityMerge /></Cut>
      <Cut from={456} dur={120}><ConnectionWeb /></Cut>
      <Cut from={576} dur={84}><RiskBars /></Cut>
      <Cut from={660} dur={114}><ProofFlash /></Cut>
      <Cut from={774} dur={54}><AskNessusGfx /></Cut>
      <Cut from={828} dur={72}><CloseFast /></Cut>
    </AbsoluteFill>
  );
};
