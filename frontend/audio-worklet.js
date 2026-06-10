class ClassroomAudioCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = options.processorOptions || {};
    this.targetRate = settings.targetSampleRate || 16000;
    this.chunkDurationMs = settings.chunkDurationMs || 200;
    this.targetInputSamples = Math.round(sampleRate * this.chunkDurationMs / 1000);
    this.buffers = [];
    this.sampleCount = 0;
    this.port.onmessage = (event) => {
      if (event.data?.type === "flush") {
        if (this.sampleCount > 0) this.emitChunk(this.sampleCount);
        this.port.postMessage({ type: "flushed" });
      }
    };
  }

  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    if (input?.length) {
      this.buffers.push(new Float32Array(input));
      this.sampleCount += input.length;
      while (this.sampleCount >= this.targetInputSamples) this.emitChunk(this.targetInputSamples);
    }
    outputs[0]?.forEach((channel) => channel.fill(0));
    return true;
  }

  emitChunk(sampleTotal) {
    const chunk = new Float32Array(sampleTotal);
    let written = 0;
    while (written < chunk.length) {
      const current = this.buffers[0];
      const take = Math.min(current.length, chunk.length - written);
      chunk.set(current.subarray(0, take), written);
      written += take;
      if (take === current.length) this.buffers.shift();
      else this.buffers[0] = current.subarray(take);
      this.sampleCount -= take;
    }

    const resampled = sincResample(chunk, sampleRate, this.targetRate);
    this.port.postMessage(
      {
        type: "audio",
        samples: resampled,
        durationMs: Math.max(1, Math.round(sampleTotal / sampleRate * 1000)),
        metrics: measureAudio(chunk),
      },
      [resampled.buffer],
    );
  }
}

function sinc(value) {
  return value === 0 ? 1 : Math.sin(Math.PI * value) / (Math.PI * value);
}

function sincResample(input, inputRate, outputRate) {
  if (inputRate === outputRate) return new Float32Array(input);
  const ratio = inputRate / outputRate;
  const output = new Float32Array(Math.round(input.length / ratio));
  const radius = 12;

  for (let outputIndex = 0; outputIndex < output.length; outputIndex += 1) {
    const center = outputIndex * ratio;
    const start = Math.max(0, Math.floor(center) - radius + 1);
    const end = Math.min(input.length, Math.floor(center) + radius + 1);
    let weighted = 0;
    let weightTotal = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) {
      const distance = center - inputIndex;
      const weight = sinc(distance) * sinc(distance / radius);
      weighted += input[inputIndex] * weight;
      weightTotal += weight;
    }
    output[outputIndex] = weightTotal ? weighted / weightTotal : 0;
  }
  return output;
}

function measureAudio(samples) {
  let squared = 0;
  let peak = 0;
  let clipped = 0;
  for (const sample of samples) {
    const absolute = Math.abs(sample);
    squared += sample * sample;
    peak = Math.max(peak, absolute);
    if (absolute >= 0.98) clipped += 1;
  }
  return {
    rms: Math.sqrt(squared / Math.max(1, samples.length)),
    peak,
    clippedRatio: clipped / Math.max(1, samples.length),
  };
}

registerProcessor("classroom-audio-capture", ClassroomAudioCaptureProcessor);
