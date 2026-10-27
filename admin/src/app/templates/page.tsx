'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

type Template = {
  id: string;
  name: string;
  modality: string;
  body_part: string | null;
  description: string | null;
  is_default: boolean;
  sections: { name: string; key: string; type: string; default?: string }[];
  macros: Record<string, string> | null;
  normal_template: string | null;
  impression_template: string | null;
};

const EMPTY_FORM = {
  name: '',
  modality: 'CT',
  description: '',
  body_part: '',
  normal_template: '',
  impression_template: '',
};

interface FormErrors {
  name?: string;
}

type PreviewTab = 'edit' | 'preview';

function MarkdownTextarea({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [tab, setTab] = useState<PreviewTab>('edit');

  // Safe markdown rendering — no dangerouslySetInnerHTML
  const renderMarkdown = (text: string) => {
    if (!text) return <span className="text-gray-400 italic">내용 없음</span>;
    const lines = text.split('\n');
    return lines.map((line, i) => {
      // Parse inline formatting into React elements
      const parseInline = (s: string): (string | React.ReactElement)[] => {
        const parts: (string | React.ReactElement)[] = [];
        let remaining = s;
        let key = 0;
        const regex = /\*\*(.*?)\*\*|\*(.*?)\*|`(.*?)`/g;
        let lastIndex = 0;
        let match;
        while ((match = regex.exec(remaining)) !== null) {
          if (match.index > lastIndex) {
            parts.push(remaining.slice(lastIndex, match.index));
          }
          if (match[1] !== undefined) {
            parts.push(<strong key={key++}>{match[1]}</strong>);
          } else if (match[2] !== undefined) {
            parts.push(<em key={key++}>{match[2]}</em>);
          } else if (match[3] !== undefined) {
            parts.push(<code key={key++} className="bg-gray-100 px-1 rounded text-xs font-mono">{match[3]}</code>);
          }
          lastIndex = regex.lastIndex;
        }
        if (lastIndex < remaining.length) {
          parts.push(remaining.slice(lastIndex));
        }
        return parts.length ? parts : [remaining];
      };

      if (line.startsWith('# ')) {
        return <div key={i} className="text-base"><strong>{parseInline(line.slice(2))}</strong></div>;
      } else if (line.startsWith('## ')) {
        return <div key={i}><strong>{parseInline(line.slice(3))}</strong></div>;
      } else if (line.startsWith('- ')) {
        return <div key={i} className="ml-3">{'\u2022 '}{parseInline(line.slice(2))}</div>;
      }
      return <div key={i}>{line ? parseInline(line) : '\u00A0'}</div>;
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs text-gray-500">{label}</label>
        <div className="flex border rounded overflow-hidden text-xs">
          <button
            type="button"
            onClick={() => setTab('edit')}
            className={`px-2 py-0.5 ${tab === 'edit' ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
          >
            편집
          </button>
          <button
            type="button"
            onClick={() => setTab('preview')}
            className={`px-2 py-0.5 ${tab === 'preview' ? 'bg-primary text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
          >
            미리보기
          </button>
        </div>
      </div>
      {tab === 'edit' ? (
        <textarea
          className="w-full border rounded px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary"
          rows={4}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
        />
      ) : (
        <div className="w-full border rounded px-3 py-2 text-xs bg-gray-50 min-h-[96px] leading-relaxed">
          {renderMarkdown(value)}
        </div>
      )}
      <p className="text-[10px] text-gray-400 mt-0.5">**굵게**, *기울임*, `코드`, # 제목, - 목록 지원</p>
    </div>
  );
}

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<Template | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const [sortField, setSortField] = useState<'name' | 'modality'>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [modalityFilterList, setModalityFilterList] = useState('');

  const showMsg = (text: string, type: 'success' | 'error' = 'success') => {
    setMsg(text);
    setMsgType(type);
    setTimeout(() => setMsg(''), 3000);
  };

  const loadTemplates = async () => {
    try {
      const result: any = await apiFetch('/api/v1/templates');
      setTemplates(result.results || result.templates || []);
    } catch (e: any) {
      showMsg(`템플릿 로드 실패: ${e.message}`, 'error');
    }
  };

  useEffect(() => {
    loadTemplates();
  }, []);

  const validateForm = (): boolean => {
    const errors: FormErrors = {};
    if (!form.name.trim()) {
      errors.name = '템플릿 이름을 입력하세요.';
    }
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSave = async () => {
    if (!validateForm()) return;
    try {
      const body = {
        name: form.name.trim(),
        modality: form.modality,
        description: form.description || null,
        body_part: form.body_part || null,
        normal_template: form.normal_template || null,
        impression_template: form.impression_template || null,
      };
      if (editingId) {
        await apiFetch(`/api/v1/templates/${editingId}`, { method: 'PUT', body: JSON.stringify(body) });
        showMsg('템플릿이 수정되었습니다.');
      } else {
        await apiFetch('/api/v1/templates', { method: 'POST', body: JSON.stringify(body) });
        showMsg('템플릿이 생성되었습니다.');
      }
      setShowForm(false);
      setForm(EMPTY_FORM);
      setEditingId(null);
      setFormErrors({});
      loadTemplates();
    } catch (e: any) {
      showMsg(`오류: ${e.message}`, 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
      await apiFetch(`/api/v1/templates/${id}`, { method: 'DELETE' });
      showMsg('템플릿이 삭제되었습니다.');
      setSelected(null);
      loadTemplates();
    } catch (e: any) {
      showMsg(`삭제 실패: ${e.message}`, 'error');
    }
  };

  const handleEdit = (template: Template) => {
    setEditingId(template.id);
    setForm({
      name: template.name,
      modality: template.modality,
      description: template.description || '',
      body_part: template.body_part || '',
      normal_template: template.normal_template || '',
      impression_template: template.impression_template || '',
    });
    setFormErrors({});
    setShowForm(true);
  };

  const handleSort = (field: 'name' | 'modality') => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const SortIcon = ({ field }: { field: 'name' | 'modality' }) => {
    if (sortField !== field) return <span className="ml-1 text-gray-300 text-xs">↕</span>;
    return <span className="ml-1 text-xs">{sortDir === 'asc' ? '↑' : '↓'}</span>;
  };

  const filteredTemplates = templates
    .filter(t => !modalityFilterList || t.modality === modalityFilterList)
    .sort((a, b) => {
      const aVal = a[sortField] || '';
      const bVal = b[sortField] || '';
      return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });

  const modalityColors: Record<string, string> = {
    CT: 'bg-purple-100 text-purple-700',
    MR: 'bg-green-100 text-green-700',
    CR: 'bg-blue-100 text-blue-700',
    DX: 'bg-blue-100 text-blue-700',
    US: 'bg-yellow-100 text-yellow-700',
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">판독 리포트 템플릿</h1>
        <button
          onClick={() => { setEditingId(null); setForm(EMPTY_FORM); setFormErrors({}); setShowForm(true); }}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary-dark"
        >
          + 템플릿 생성
        </button>
      </div>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msgType === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-green-50 text-green-800'}`}>
          {msg}
        </div>
      )}

      {/* Modality Filter */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-sm text-gray-500">모달리티 필터:</span>
        {['', 'CT', 'MR', 'CR', 'DX', 'US'].map(m => (
          <button
            key={m}
            onClick={() => setModalityFilterList(m)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition ${modalityFilterList === m ? 'bg-primary text-white border-primary' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
          >
            {m || '전체'}
          </button>
        ))}
      </div>

      {/* Create / Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center overflow-y-auto" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-2xl m-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">{editingId ? '템플릿 수정' : '템플릿 생성'}</h2>

            <div className="space-y-4 text-sm max-h-[70vh] overflow-y-auto pr-1">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-gray-500">이름 *</label>
                  <input
                    className={`w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary ${formErrors.name ? 'border-red-400' : ''}`}
                    value={form.name}
                    onChange={e => setForm({...form, name: e.target.value})}
                    placeholder="예: 흉부 CT 기본 템플릿"
                  />
                  {formErrors.name && <p className="text-red-500 text-xs mt-0.5">{formErrors.name}</p>}
                </div>
                <div>
                  <label className="text-xs text-gray-500">모달리티</label>
                  <select
                    className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                    value={form.modality}
                    onChange={e => setForm({...form, modality: e.target.value})}
                  >
                    <option>CT</option>
                    <option>MR</option>
                    <option>CR</option>
                    <option>DX</option>
                    <option>US</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-500">설명</label>
                <input
                  className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                  value={form.description}
                  onChange={e => setForm({...form, description: e.target.value})}
                  placeholder="템플릿 설명..."
                />
              </div>

              <div>
                <label className="text-xs text-gray-500">검사 부위</label>
                <input
                  className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
                  value={form.body_part}
                  onChange={e => setForm({...form, body_part: e.target.value})}
                  placeholder="CHEST, HEAD, ABDOMEN..."
                />
              </div>

              <MarkdownTextarea
                label="정상 소견 템플릿"
                value={form.normal_template}
                onChange={v => setForm({...form, normal_template: v})}
                placeholder="# 흉부 CT&#10;## 폐&#10;- 정상 음영&#10;## 심장&#10;- 정상 심비대 없음"
              />

              <MarkdownTextarea
                label="결론 템플릿"
                value={form.impression_template}
                onChange={v => setForm({...form, impression_template: v})}
                placeholder="**결론:** 이상 소견 없음&#10;추가 검사 불필요"
              />
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => { setShowForm(false); setFormErrors({}); }}
                className="px-4 py-2 border rounded text-sm"
              >
                취소
              </button>
              <button
                onClick={handleSave}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold hover:bg-primary-dark"
              >
                {editingId ? '수정' : '생성'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Template List */}
        <div>
          <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
            <span>정렬:</span>
            <button
              onClick={() => handleSort('name')}
              className={`px-2 py-0.5 rounded border ${sortField === 'name' ? 'border-primary text-primary' : 'border-gray-300 hover:bg-gray-50'}`}
            >
              이름<SortIcon field="name" />
            </button>
            <button
              onClick={() => handleSort('modality')}
              className={`px-2 py-0.5 rounded border ${sortField === 'modality' ? 'border-primary text-primary' : 'border-gray-300 hover:bg-gray-50'}`}
            >
              모달리티<SortIcon field="modality" />
            </button>
          </div>
          <div className="space-y-2">
            {filteredTemplates.length === 0 ? (
              <div className="text-center py-8 text-gray-400 text-sm bg-white border rounded-lg">
                <p>템플릿이 없습니다</p>
                {modalityFilterList && (
                  <button
                    onClick={() => setModalityFilterList('')}
                    className="mt-2 text-primary underline text-xs"
                  >
                    필터 초기화
                  </button>
                )}
              </div>
            ) : (
              filteredTemplates.map(t => (
                <button
                  key={t.id}
                  onClick={() => setSelected(t)}
                  className={`w-full text-left p-4 rounded-lg border shadow-sm transition ${selected?.id === t.id ? 'border-primary bg-blue-50' : 'bg-white hover:bg-gray-50'}`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${modalityColors[t.modality] || 'bg-gray-100 text-gray-600'}`}>
                      {t.modality}
                    </span>
                    <span className="font-semibold text-sm">{t.name}</span>
                    {t.is_default && (
                      <span className="ml-auto text-[10px] bg-yellow-100 text-yellow-800 px-1.5 rounded">기본</span>
                    )}
                  </div>
                  {t.description && (
                    <p className="text-xs text-gray-500 mt-1 truncate">{t.description}</p>
                  )}
                  <div className="flex gap-3 mt-1 text-[10px] text-gray-400">
                    {t.body_part && <span>{t.body_part}</span>}
                    {t.sections?.length > 0 && <span>{t.sections.length}개 섹션</span>}
                    {t.macros && Object.keys(t.macros).length > 0 && <span>{Object.keys(t.macros).length}개 단축어</span>}
                    {t.normal_template && <span>정상템플릿</span>}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Template Detail */}
        <div className="md:col-span-2">
          {selected ? (
            <div className="bg-white rounded-lg border shadow-sm p-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${modalityColors[selected.modality] || 'bg-gray-100'}`}>
                      {selected.modality}
                    </span>
                    {selected.is_default && (
                      <span className="text-[10px] bg-yellow-100 text-yellow-800 px-1.5 rounded">기본 템플릿</span>
                    )}
                  </div>
                  <h2 className="text-xl font-bold">{selected.name}</h2>
                  {selected.description && (
                    <p className="text-sm text-gray-500">{selected.description}</p>
                  )}
                  {selected.body_part && (
                    <p className="text-xs text-gray-400 mt-0.5">부위: {selected.body_part}</p>
                  )}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => handleEdit(selected)}
                    className="bg-blue-50 text-blue-700 hover:bg-blue-100 px-3 py-1.5 rounded text-xs font-medium transition"
                  >
                    수정
                  </button>
                  <button
                    onClick={() => {
                      setEditingId(null);
                      setForm({
                        name: `${selected.name} (복사)`,
                        modality: selected.modality,
                        description: selected.description || '',
                        body_part: selected.body_part || '',
                        normal_template: selected.normal_template || '',
                        impression_template: selected.impression_template || '',
                      });
                      setShowForm(true);
                    }}
                    className="bg-gray-50 text-gray-700 hover:bg-gray-100 px-3 py-1.5 rounded text-xs font-medium transition"
                  >
                    복사
                  </button>
                  <button
                    onClick={() => handleDelete(selected.id)}
                    className="bg-red-50 text-red-600 hover:bg-red-100 px-3 py-1.5 rounded text-xs font-medium transition"
                  >
                    삭제
                  </button>
                </div>
              </div>

              {selected.normal_template && (
                <div className="mb-4">
                  <h3 className="font-semibold text-sm mb-1 text-gray-700">정상 소견 템플릿</h3>
                  <div className="text-sm bg-green-50 rounded p-3 text-green-800 font-mono whitespace-pre-wrap text-xs leading-relaxed">
                    {selected.normal_template}
                  </div>
                </div>
              )}

              {selected.impression_template && (
                <div className="mb-4">
                  <h3 className="font-semibold text-sm mb-1 text-gray-700">결론 템플릿</h3>
                  <div className="text-sm bg-blue-50 rounded p-3 text-blue-800 font-mono whitespace-pre-wrap text-xs leading-relaxed">
                    {selected.impression_template}
                  </div>
                </div>
              )}

              {selected.sections && selected.sections.length > 0 && (
                <div className="mb-4">
                  <h3 className="font-semibold text-sm mb-2 text-gray-700">리포트 섹션</h3>
                  <div className="space-y-1">
                    {selected.sections.map((s, i) => (
                      <div key={i} className="flex items-center gap-3 bg-gray-50 rounded px-3 py-2 text-xs">
                        <span className="font-medium text-gray-800 w-24">{s.name}</span>
                        <code className="text-gray-400 font-mono">{s.key}</code>
                        <span className="text-gray-300">·</span>
                        <span className="text-gray-400">{s.type}</span>
                        {s.default && <span className="ml-auto text-gray-500 truncate max-w-[200px]">{s.default}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!selected.normal_template && !selected.impression_template && (!selected.sections || selected.sections.length === 0) && (
                <p className="text-gray-400 text-sm text-center py-6">템플릿 내용이 없습니다. 수정 버튼을 눌러 내용을 추가하세요.</p>
              )}

              {selected.macros && Object.keys(selected.macros).length > 0 && (
                <div>
                  <h3 className="font-semibold text-sm mb-2 text-gray-700">단축어 (Macros)</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(selected.macros).map(([key, val]) => (
                      <div key={key} className="bg-gray-50 rounded p-2 text-xs">
                        <code className="text-primary font-mono font-bold">{key}</code>
                        <span className="text-gray-400 mx-1">→</span>
                        <span className="text-gray-700">{val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white rounded-lg border shadow-sm p-12 text-center text-gray-400">
              <p className="text-lg mb-2">왼쪽에서 템플릿을 선택하세요</p>
              <p className="text-sm">총 {templates.length}개 템플릿</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
