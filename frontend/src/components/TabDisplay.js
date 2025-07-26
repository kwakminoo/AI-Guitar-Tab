import React, { useState, useRef } from 'react';
import { FaDownload, FaPrint, FaExpand, FaCompress, FaMusic } from 'react-icons/fa';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';

const TabDisplay = ({ tabData, chords, analysisInfo }) => {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedMeasure, setSelectedMeasure] = useState(0);
  const tabRef = useRef();

  const generateTextTab = () => {
    if (!tabData || !tabData.measures) return '';

    let tabText = `${analysisInfo?.filename || '곡제목'}\n`;
    tabText += `키: ${analysisInfo?.key || 'C'} | 템포: ${Math.round(analysisInfo?.tempo) || 120} BPM\n`;
    tabText += `카포: ${analysisInfo?.capo_position || 0}프렛 | 연주비율: ${Math.round((analysisInfo?.arpeggio_ratio || 0.5) * 100)}% 아르페지오\n\n`;

    tabData.measures.forEach((measure, measureIndex) => {
      tabText += `마디 ${measure.measure_number}:\n`;
      
      // 코드 표시
      const chordLine = measure.chords.map(chord => 
        `${chord.chord}(${chord.style === 'arpeggio' ? 'A' : 'S'})`
      ).join(' - ');
      tabText += `코드: ${chordLine}\n`;

      // 타브 표시 (간단한 형태)
      if (measure.tab_notation && measure.tab_notation.length > 0) {
        const strings = ['E|', 'B|', 'G|', 'D|', 'A|', 'E|'];
        const tabLines = strings.map(() => '');

        measure.tab_notation.forEach(note => {
          if (note.type === 'strum') {
            strings.forEach((_, stringIndex) => {
              const stringNote = note.strings?.find(s => s.string === stringIndex + 1);
              if (stringNote) {
                tabLines[stringIndex] += `${stringNote.fret}-`;
              } else {
                tabLines[stringIndex] += 'x-';
              }
            });
          } else if (note.string && note.fret !== undefined) {
            const stringIndex = note.string - 1;
            if (stringIndex >= 0 && stringIndex < 6) {
              tabLines[stringIndex] += `${note.fret}-`;
            }
          }
        });

        strings.forEach((stringName, index) => {
          tabText += stringName + (tabLines[index] || '') + '\n';
        });
      }
      
      tabText += '\n';
    });

    return tabText;
  };

  const downloadPDF = async () => {
    const element = tabRef.current;
    if (!element) return;

    try {
      const canvas = await html2canvas(element, {
        scale: 2,
        backgroundColor: '#ffffff'
      });
      
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF();
      
      const imgWidth = 210;
      const pageHeight = 295;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      let heightLeft = imgHeight;
      
      let position = 0;
      
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
      heightLeft -= pageHeight;
      
      while (heightLeft >= 0) {
        position = heightLeft - imgHeight;
        pdf.addPage();
        pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
        heightLeft -= pageHeight;
      }
      
      pdf.save(`${analysisInfo?.filename || 'guitar-tab'}.pdf`);
    } catch (error) {
      console.error('PDF 생성 오류:', error);
      alert('PDF 생성 중 오류가 발생했습니다.');
    }
  };

  const downloadText = () => {
    const textContent = generateTextTab();
    const blob = new Blob([textContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `${analysisInfo?.filename || 'guitar-tab'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const renderMeasure = (measure) => {
    return (
      <div key={measure.measure_number} className="border rounded-lg p-4 mb-4 bg-gray-50">
        <div className="flex items-center justify-between mb-3">
          <h4 className="font-semibold text-guitar-700">마디 {measure.measure_number}</h4>
          <div className="text-sm text-gray-600">
            {measure.chords?.length || 0}개 코드
          </div>
        </div>

        {/* 코드 표시 */}
        <div className="mb-3">
          <div className="flex flex-wrap gap-2">
            {measure.chords?.map((chord, index) => (
              <div key={index} className="bg-white rounded-lg px-3 py-2 border">
                <div className="font-semibold text-lg text-guitar-700">{chord.chord}</div>
                <div className="text-xs text-gray-500">
                  {chord.style === 'arpeggio' ? '아르페지오' : '스트로크'}
                </div>
              </div>
            )) || []}
          </div>
        </div>

        {/* 타브 노테이션 */}
        {measure.tab_notation && measure.tab_notation.length > 0 && (
          <div className="tab-notation bg-white rounded-lg p-4 font-mono text-sm overflow-x-auto">
            {renderTabNotation(measure.tab_notation)}
          </div>
        )}
      </div>
    );
  };

  const renderTabNotation = (notation) => {
    // 6줄 기타 타브 초기화
    const strings = [
      'e|', // 1번줄 (가장 높은음)
      'B|', // 2번줄
      'G|', // 3번줄
      'D|', // 4번줄
      'A|', // 5번줄
      'E|'  // 6번줄 (가장 낮은음)
    ];

    const tabLines = strings.map(() => '');
    
    notation.forEach((note, noteIndex) => {
      if (note.type === 'strum') {
        // 스트로크 표시
        note.strings?.forEach(stringInfo => {
          const stringIndex = 6 - stringInfo.string; // 인덱스 변환 (1번줄=0, 6번줄=5)
          if (stringIndex >= 0 && stringIndex < 6) {
            tabLines[stringIndex] += `${stringInfo.fret}`;
          }
        });
        
        // 모든 줄에 구분자 추가
        tabLines.forEach((_, index) => {
          tabLines[index] += '-';
        });
        
      } else if (note.string && note.fret !== undefined) {
        // 개별 노트 표시
        const stringIndex = 6 - note.string; // 인덱스 변환
        if (stringIndex >= 0 && stringIndex < 6) {
          tabLines[stringIndex] += `${note.fret}-`;
        }
        
        // 다른 줄에는 공백 추가
        tabLines.forEach((_, index) => {
          if (index !== stringIndex) {
            tabLines[index] += '--';
          }
        });
      } else if (note.type === 'rest') {
        // 쉼표 표시
        tabLines.forEach((_, index) => {
          tabLines[index] += '---';
        });
      }
    });

    return strings.map((stringName, index) => (
      <div key={index} className="leading-tight">
        {stringName}{tabLines[index]}
      </div>
    ));
  };

  return (
    <div className={`bg-white rounded-xl shadow-lg overflow-hidden ${isFullscreen ? 'fixed inset-4 z-50' : ''}`}>
      {/* 헤더 */}
      <div className="bg-gradient-to-r from-purple-500 to-purple-600 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <FaMusic className="text-white text-xl" />
            <h3 className="text-xl font-semibold text-white">기타 타브 악보</h3>
          </div>
          
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="bg-white/20 hover:bg-white/30 text-white px-3 py-1 rounded-lg text-sm transition-colors flex items-center space-x-1"
            >
              {isFullscreen ? <FaCompress /> : <FaExpand />}
              <span>{isFullscreen ? '축소' : '확대'}</span>
            </button>
            
            <button
              onClick={downloadText}
              className="bg-white/20 hover:bg-white/30 text-white px-3 py-1 rounded-lg text-sm transition-colors flex items-center space-x-1"
            >
              <FaDownload />
              <span>TXT</span>
            </button>
            
            <button
              onClick={downloadPDF}
              className="bg-white/20 hover:bg-white/30 text-white px-3 py-1 rounded-lg text-sm transition-colors flex items-center space-x-1"
            >
              <FaDownload />
              <span>PDF</span>
            </button>
          </div>
        </div>
      </div>

      <div className="p-6" ref={tabRef}>
        {/* 악보 정보 */}
        {analysisInfo && (
          <div className="mb-6 p-4 bg-gray-50 rounded-lg">
            <h4 className="font-semibold text-lg mb-2">{analysisInfo.filename}</h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-gray-600">키:</span>
                <span className="ml-2 font-semibold">{analysisInfo.key}</span>
              </div>
              <div>
                <span className="text-gray-600">템포:</span>
                <span className="ml-2 font-semibold">{Math.round(analysisInfo.tempo)} BPM</span>
              </div>
              <div>
                <span className="text-gray-600">카포:</span>
                <span className="ml-2 font-semibold">
                  {analysisInfo.capo_position || 0}프렛
                </span>
              </div>
              <div>
                <span className="text-gray-600">연주 스타일:</span>
                <span className="ml-2 font-semibold">
                  {Math.round((analysisInfo.arpeggio_ratio || 0.5) * 100)}% 아르페지오
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 마디 선택 (많은 마디가 있을 때) */}
        {tabData?.measures && tabData.measures.length > 5 && (
          <div className="mb-4">
            <div className="flex items-center space-x-2 text-sm">
              <span className="text-gray-600">마디 선택:</span>
              <select
                value={selectedMeasure}
                onChange={(e) => setSelectedMeasure(parseInt(e.target.value))}
                className="border rounded px-3 py-1"
              >
                <option value={0}>모든 마디</option>
                {tabData.measures.map((measure, index) => (
                  <option key={index} value={measure.measure_number}>
                    마디 {measure.measure_number}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* 타브 악보 표시 */}
        <div className="max-h-96 overflow-y-auto">
          {tabData?.measures && tabData.measures.length > 0 ? (
            <div>
              {selectedMeasure === 0 
                ? tabData.measures.map(renderMeasure)
                : tabData.measures
                    .filter(m => m.measure_number === selectedMeasure)
                    .map(renderMeasure)
              }
            </div>
          ) : (
            <div className="text-center py-12">
              <FaMusic className="text-6xl text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-gray-600 mb-2">
                타브 악보가 없습니다
              </h3>
              <p className="text-gray-500">
                음악 파일을 분석하면 타브 악보가 여기에 표시됩니다
              </p>
            </div>
          )}
        </div>

        {/* 설명 */}
        <div className="mt-6 p-4 bg-blue-50 rounded-lg text-sm">
          <h5 className="font-semibold text-blue-800 mb-2">📚 타브 악보 읽는 법:</h5>
          <ul className="text-blue-700 space-y-1">
            <li>• 숫자는 프렛 번호를 나타냅니다 (0 = 오픈 스트링)</li>
            <li>• A = 아르페지오 연주, S = 스트로크 연주</li>
            <li>• 위에서부터 1번줄(E), 2번줄(B), 3번줄(G), 4번줄(D), 5번줄(A), 6번줄(E)</li>
            <li>• - 기호는 시간의 흐름을 나타냅니다</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default TabDisplay;