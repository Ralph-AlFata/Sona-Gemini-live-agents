export async function startAudioRecorderWorklet(
  audioRecorderHandler: (pcmData: ArrayBuffer) => void,
): Promise<[AudioWorkletNode, AudioContext, MediaStream]> {
  const audioRecorderContext = new AudioContext({ sampleRate: 16000 });
  const workletURL = new URL("./pcm-recorder-processor.js", import.meta.url);
  await audioRecorderContext.audioWorklet.addModule(workletURL);

  const micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1 },
  });
  const source = audioRecorderContext.createMediaStreamSource(micStream);
  const audioRecorderNode = new AudioWorkletNode(
    audioRecorderContext,
    "pcm-recorder-processor",
  );

  source.connect(audioRecorderNode);
  audioRecorderNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
    const pcmData = convertFloat32ToPCM(event.data);
    audioRecorderHandler(pcmData);
  };

  return [audioRecorderNode, audioRecorderContext, micStream];
}

export function stopMicrophone(micStream: MediaStream | null): void {
  if (!micStream) return;
  micStream.getTracks().forEach((track) => track.stop());
}

function convertFloat32ToPCM(inputData: Float32Array): ArrayBuffer {
  const pcm16 = new Int16Array(inputData.length);
  for (let i = 0; i < inputData.length; i++) {
    const value = Math.max(-1, Math.min(1, inputData[i] ?? 0));
    pcm16[i] = value * 0x7fff;
  }
  return pcm16.buffer;
}
