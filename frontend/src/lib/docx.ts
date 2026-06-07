// Minimal, dependency-free .docx text extractor for the browser.
//
// A .docx is a ZIP archive; the visible body text lives in `word/document.xml`.
// `File.text()` returns the raw ZIP bytes (garbled), so adverse keywords in an
// uploaded credit file never reach the backend. This reads the ZIP central
// directory, inflates `word/document.xml` with the platform `DecompressionStream`
// ('deflate-raw'), and strips the XML to plain text — no external packages.

const ZIP_EOCD_SIG = 0x06054b50; // End Of Central Directory
const ZIP_CDH_SIG = 0x02014b50; // Central Directory File Header

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  // Use a fresh ArrayBuffer slice so the stream sees exactly these bytes.
  const input = bytes.slice();
  const stream = new Response(input).body!.pipeThrough(
    new DecompressionStream("deflate-raw"),
  );
  const buf = await new Response(stream).arrayBuffer();
  return new Uint8Array(buf);
}

function findEocdOffset(view: DataView): number {
  // EOCD is at the end; scan backwards (comment can be up to 65535 bytes).
  const len = view.byteLength;
  const minOffset = Math.max(0, len - 65557);
  for (let i = len - 22; i >= minOffset; i--) {
    if (view.getUint32(i, true) === ZIP_EOCD_SIG) return i;
  }
  return -1;
}

function xmlToText(xml: string): string {
  return xml
    // Paragraph and line breaks become newlines.
    .replace(/<\/w:p>/g, "\n")
    .replace(/<w:br\s*\/?>/g, "\n")
    .replace(/<w:tab\s*\/?>/g, "\t")
    // Drop every remaining tag.
    .replace(/<[^>]+>/g, "")
    // Decode the handful of XML entities Word emits.
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, d: string) => String.fromCharCode(Number(d)))
    .replace(/\u00a0/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Extract the plain body text from a .docx File. Returns "" on any failure
 * (unsupported browser, malformed file, etc.) so callers can fall back safely.
 */
export async function extractDocxText(file: File): Promise<string> {
  try {
    const ab = await file.arrayBuffer();
    const bytes = new Uint8Array(ab);
    const view = new DataView(ab);

    const eocd = findEocdOffset(view);
    if (eocd < 0) return "";
    const cdCount = view.getUint16(eocd + 10, true);
    let cdOffset = view.getUint32(eocd + 16, true);

    let dataStart = -1;
    let compMethod = -1;
    let compSize = -1;

    for (let i = 0; i < cdCount; i++) {
      if (cdOffset + 4 > bytes.length || view.getUint32(cdOffset, true) !== ZIP_CDH_SIG) {
        break;
      }
      const method = view.getUint16(cdOffset + 10, true);
      const compressedSize = view.getUint32(cdOffset + 20, true);
      const nameLen = view.getUint16(cdOffset + 28, true);
      const extraLen = view.getUint16(cdOffset + 30, true);
      const commentLen = view.getUint16(cdOffset + 32, true);
      const localOffset = view.getUint32(cdOffset + 42, true);
      const name = new TextDecoder().decode(
        bytes.subarray(cdOffset + 46, cdOffset + 46 + nameLen),
      );

      if (name === "word/document.xml") {
        // Resolve the data start from the LOCAL header (its name/extra lengths
        // can differ from the central directory's).
        const localNameLen = view.getUint16(localOffset + 26, true);
        const localExtraLen = view.getUint16(localOffset + 28, true);
        dataStart = localOffset + 30 + localNameLen + localExtraLen;
        compMethod = method;
        compSize = compressedSize;
        break;
      }
      cdOffset += 46 + nameLen + extraLen + commentLen;
    }

    if (dataStart < 0 || compSize <= 0) return "";
    const raw = bytes.subarray(dataStart, dataStart + compSize);
    let xmlBytes: Uint8Array;
    if (compMethod === 0) {
      xmlBytes = raw; // stored
    } else if (compMethod === 8) {
      xmlBytes = await inflateRaw(raw); // deflate
    } else {
      return "";
    }
    const xml = new TextDecoder("utf-8").decode(xmlBytes);
    return xmlToText(xml);
  } catch {
    return "";
  }
}
