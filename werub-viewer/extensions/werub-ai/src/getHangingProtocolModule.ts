/**
 * 모달리티별 자동 Hanging Protocol (viewer-ux A, v13.17).
 *
 * 'werubAutoMPR' = 코어 mpr HP의 클론 + protocolMatchingRules.
 * 매칭은 mode의 hangingProtocol이 **배열**일 때만 동작한다(문자열이면 직접 적용) —
 * longitudinal 모드가 ['werubAutoMPR', 'default']를 지정(werub-source.patch).
 * required 규칙이 커스텀 속성 'werubHasReconstructable'(index.ts에서 등록,
 * displaySets에 재구성 가능 시리즈 존재)이라 단면/SR-only 검사에서는 매칭 실패
 * → 엔진이 'default'(1×1)로 폴백. 적용 단계 실패(빈 볼륨)가 원천 차단된다.
 * isPreset: false — 레이아웃 Advanced 메뉴(큐레이션)에는 노출하지 않는다.
 */

const VOI_SYNC_GROUP = {
  type: 'voi',
  id: 'mpr',
  source: true,
  target: true,
  options: { syncColormap: true },
};

const HYDRATE_SEG_SYNC_GROUP = {
  type: 'hydrateseg',
  id: 'sameFORId',
  source: true,
  target: true,
  options: { matchingRules: ['sameFOR'] },
};

function mprViewport(viewportId: string, orientation: string) {
  return {
    viewportOptions: {
      viewportId,
      toolGroupId: 'mpr',
      viewportType: 'volume',
      orientation,
      initialImageOptions: { preset: 'middle' },
      syncGroups: [VOI_SYNC_GROUP, HYDRATE_SEG_SYNC_GROUP],
    },
    displaySets: [{ id: 'activeDisplaySet' }],
  };
}

const werubAutoMPR = {
  id: 'werubAutoMPR',
  name: '자동 MPR',
  locked: true,
  icon: 'layout-advanced-mpr',
  isPreset: false,
  createdDate: '2026-07-11',
  modifiedDate: '2026-07-11',
  availableTo: {},
  editableBy: {},
  numberOfPriorsReferenced: 0,
  protocolMatchingRules: [
    {
      id: 'werubReconstructable',
      weight: 10,
      attribute: 'werubHasReconstructable',
      constraint: { equals: { value: true } },
      required: true,
    },
    // 모달리티 가중치(선택) — CT/MR이면 우선순위를 높인다
    { id: 'werubCT', weight: 2, attribute: 'ModalitiesInStudy', constraint: { contains: { value: 'CT' } } },
    { id: 'werubMR', weight: 2, attribute: 'ModalitiesInStudy', constraint: { contains: { value: 'MR' } } },
  ],
  imageLoadStrategy: 'nth',
  callbacks: {},
  displaySetSelectors: {
    activeDisplaySet: {
      seriesMatchingRules: [
        {
          weight: 1,
          attribute: 'isReconstructable',
          constraint: { equals: { value: true } },
          required: true,
        },
      ],
    },
  },
  stages: [
    {
      name: 'MPR 1x3',
      viewportStructure: {
        layoutType: 'grid',
        properties: {
          rows: 1,
          columns: 3,
          layoutOptions: [
            { x: 0, y: 0, width: 1 / 3, height: 1 },
            { x: 1 / 3, y: 0, width: 1 / 3, height: 1 },
            { x: 2 / 3, y: 0, width: 1 / 3, height: 1 },
          ],
        },
      },
      viewports: [
        mprViewport('mpr-axial', 'axial'),
        mprViewport('mpr-sagittal', 'sagittal'),
        mprViewport('mpr-coronal', 'coronal'),
      ],
    },
  ],
};

export default function getHangingProtocolModule() {
  return [
    {
      name: werubAutoMPR.id,
      protocol: werubAutoMPR,
    },
  ];
}
