import { describe, expect, it } from 'vitest'

import { actionRequestBody, apiErrorDetails, apiErrorFromResponse, type WorkflowInput } from './client'

describe('apiErrorFromResponse', () => {
  it('preserves field and issue locations from a validation response', () => {
    const error = apiErrorFromResponse(400, '400 Bad Request', {
      error: '의뢰서 입력 오류',
      fields: { analyst_id: '담당자를 골라야 한다' },
      issues: [{ location: 'analysis_overview.model_suffix', message: '모델명이 필요하다' }],
    })

    expect(error.message).toBe('의뢰서 입력 오류')
    expect(error.fields).toEqual({ analyst_id: '담당자를 골라야 한다' })
    expect(error.issues).toEqual([{ location: 'analysis_overview.model_suffix', message: '모델명이 필요하다' }])
    expect(apiErrorDetails(error)).toEqual([
      'analyst_id: 담당자를 골라야 한다',
      'analysis_overview.model_suffix: 모델명이 필요하다',
    ])
  })

  it('preserves target reconfirmation impact without inventing client state', () => {
    const error = apiErrorFromResponse(409, '409 Conflict', {
      error: '확인 필요',
      impact: { pms_cleared: true, hidden_groups: ['supply_air'] },
    })

    expect(error.status).toBe(409)
    expect(error.impact).toEqual({ pms_cleared: true, hidden_groups: ['supply_air'] })
  })

  it('returns server-provided impact messages for the common error display', () => {
    const error = apiErrorFromResponse(409, '409 Conflict', {
      error: '확인 필요',
      impact: { messages: ['선택한 PMS 프로젝트가 초기화됩니다.'] },
    })

    expect(apiErrorDetails(error)).toEqual(['선택한 PMS 프로젝트가 초기화됩니다.'])
  })
})

describe('actionRequestBody', () => {
  it('uses the server-provided HTTP keys and includes the Case reconfirmation choice', () => {
    const inputs: WorkflowInput[] = [
      { key: 'comment', request_key: 'comment', label: '설명', required: true, kind: 'textarea' },
      { key: 'form', request_key: 'form', label: '변경 의뢰서', required: true, kind: 'form_snapshot' },
      { key: 'confirm_case', request_key: 'confirm_case', label: 'Case 확인', required: false, kind: 'boolean' },
      { key: 'analyst', request_key: 'analyst_id', label: '담당자', required: true, kind: 'analyst' },
    ]

    expect(actionRequestBody(inputs, { comment: ' 변경 ', confirm_case: 'on', analyst_id: 'an-1' }, { cases: [] })).toEqual({
      comment: '변경', form: { cases: [] }, confirm_case: true, analyst_id: 'an-1',
    })
    expect(actionRequestBody(inputs, { comment: '변경', analyst_id: 'an-1' }, { cases: [] }).confirm_case).toBe(false)
  })
})
