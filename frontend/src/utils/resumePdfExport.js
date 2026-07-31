import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';

const sanitizeFileName = (value = '') => String(value)
  .replace(/[\\/:*?"<>|]/g, '-')
  .replace(/\s+/g, ' ')
  .trim() || 'tailored-resume';

export const downloadResumePdf = async (element, title) => {
  if (!element) {
    throw new Error('简历预览尚未准备完成。');
  }

  const canvas = await html2canvas(element, {
    backgroundColor: '#ffffff',
    scale: 2,
    useCORS: true,
    logging: false,
  });
  const pdf = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4', compress: true });
  const pageWidth = 210;
  const pageHeight = 297;
  const margin = 10;
  const contentWidth = pageWidth - margin * 2;
  const contentHeight = pageHeight - margin * 2;
  const millimetersPerPixel = contentWidth / canvas.width;
  const sourcePageHeight = Math.floor(contentHeight / millimetersPerPixel);

  let sourceTop = 0;
  let pageIndex = 0;
  while (sourceTop < canvas.height) {
    const sourceHeight = Math.min(sourcePageHeight, canvas.height - sourceTop);
    const pageCanvas = document.createElement('canvas');
    pageCanvas.width = canvas.width;
    pageCanvas.height = sourceHeight;
    pageCanvas.getContext('2d').drawImage(
      canvas,
      0,
      sourceTop,
      canvas.width,
      sourceHeight,
      0,
      0,
      canvas.width,
      sourceHeight,
    );
    if (pageIndex > 0) pdf.addPage();
    pdf.addImage(
      pageCanvas.toDataURL('image/jpeg', 0.96),
      'JPEG',
      margin,
      margin,
      contentWidth,
      sourceHeight * millimetersPerPixel,
      undefined,
      'FAST',
    );
    sourceTop += sourceHeight;
    pageIndex += 1;
  }

  pdf.save(`${sanitizeFileName(title)}.pdf`);
};
