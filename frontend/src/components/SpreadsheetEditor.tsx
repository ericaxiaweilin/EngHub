/**
 * SpreadsheetEditor - 基于 Univer 的类 Excel 在线电子表格组件
 *
 * MES 高频组件：FAI 首件检验实测值录入、BOM 编辑、设备点检表、报工数据填报等。
 * 支持公式计算、从 Excel 复制粘贴、筛选、条件格式等完整电子表格能力。
 *
 * 用法：
 *   const ref = useRef<SpreadsheetEditorHandle>(null)
 *   <SpreadsheetEditor ref={ref} headers={['项目','实测值','公差']} initialData={rows} height={400} />
 *   const data = ref.current?.getData()  // 获取编辑后的二维数组
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { createUniver, LocaleType, mergeLocales, type FUniver } from '@univerjs/presets'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import UniverPresetSheetsCoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN'
import '@univerjs/preset-sheets-core/lib/index.css'

export type CellValue = string | number | null | undefined

export interface SpreadsheetEditorHandle {
  /** 获取当前表格数据（二维数组，不含表头行） */
  getData: () => CellValue[][]
  /** 获取包含表头的完整数据 */
  getDataWithHeaders: () => CellValue[][]
  /** 获取完整 Univer 工作簿快照（包含公式、多个 Sheet 与基础样式） */
  getWorkbookSnapshot: () => Record<string, any> | null
  /** 获取 Univer 实例 API（高级操作） */
  getUniverAPI: () => FUniver | null
}

interface SpreadsheetEditorProps {
  /** 表头列名（渲染为第一行） */
  headers?: string[]
  /** 初始数据（二维数组） */
  initialData?: CellValue[][]
  /** 容器高度 px */
  height?: number
  /** 数据变化回调（单元格编辑后触发，含表头的完整数据） */
  onChange?: (data: CellValue[][]) => void
  /** 工作表名称 */
  sheetName?: string
  /** 已保存的 Univer 工作簿快照；传入后保留多 Sheet/公式/基础样式 */
  initialWorkbook?: Record<string, any>
}

/** 二维数组 → Univer workbookData 的 cellData */
function buildCellData(headers: string[], data: CellValue[][]) {
  const cellData: Record<number, Record<number, { v: string | number; f?: string }>> = {}
  // 表头行
  headers.forEach((h, col) => {
    if (!cellData[0]) cellData[0] = {}
    cellData[0][col] = { v: h }
  })
  // 数据行（偏移 1 行）
  data.forEach((row, r) => {
    row.forEach((val, col) => {
      if (val === null || val === undefined || val === '') return
      const ri = r + 1
      if (!cellData[ri]) cellData[ri] = {}
      if (typeof val === 'string' && val.startsWith('=')) {
        cellData[ri][col] = { v: '', f: val }
      } else {
        cellData[ri][col] = { v: typeof val === 'number' ? val : String(val) }
      }
    })
  })
  return cellData
}

/** 从 Univer 工作表读取二维数组 */
function readSheetValues(univerAPI: FUniver, maxRows: number, maxCols: number): CellValue[][] {
  try {
    const workbook = univerAPI.getActiveWorkbook()
    if (!workbook) return []
    const sheet = workbook.getActiveSheet()
    if (!sheet) return []
    const rows = Math.min(maxRows, sheet.getMaxRows())
    const cols = Math.min(maxCols, sheet.getMaxColumns())
    if (rows <= 0 || cols <= 0) return []
    const range = sheet.getRange(0, 0, rows, cols)
    const values = range.getValues() || []
    return values.map((row) => row.map((cell) => (cell === null || cell === undefined ? '' : (cell as CellValue))))
  } catch {
    return []
  }
}

const SpreadsheetEditor = forwardRef<SpreadsheetEditorHandle, SpreadsheetEditorProps>(
  ({ headers = [], initialData = [], height = 420, onChange, sheetName = 'Sheet1', initialWorkbook }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const univerRef = useRef<FUniver | null>(null)
    const onChangeRef = useRef(onChange)
    onChangeRef.current = onChange
    const headerCountRef = useRef(headers.length ? 1 : 0)
    const colCountRef = useRef(Math.max(headers.length, initialData[0]?.length || 0, 1))

    useImperativeHandle(ref, () => ({
      getData: () => {
        const all = univerRef.current ? readSheetValues(univerRef.current, 500, colCountRef.current) : []
        // 去掉表头行
        return headerCountRef.current ? all.slice(headerCountRef.current) : all
      },
      getDataWithHeaders: () => {
        return univerRef.current ? readSheetValues(univerRef.current, 500, colCountRef.current) : []
      },
      getWorkbookSnapshot: () => {
        try {
          return univerRef.current?.getActiveWorkbook()?.save() as Record<string, any> || null
        } catch {
          return null
        }
      },
      getUniverAPI: () => univerRef.current,
    }))

    useEffect(() => {
      if (!containerRef.current) return

      const { univerAPI } = createUniver({
        locale: LocaleType.ZH_CN,
        locales: {
          [LocaleType.ZH_CN]: mergeLocales(UniverPresetSheetsCoreZhCN),
        },
        presets: [
          UniverSheetsCorePreset({
            container: containerRef.current,
          }),
        ],
      })

      const workbookData = initialWorkbook || {
        id: 'mes-sheet',
        name: sheetName,
        sheetOrder: ['sheet-01'],
        sheets: {
          'sheet-01': {
            id: 'sheet-01',
            name: sheetName,
            cellData: buildCellData(headers, initialData),
            rowCount: Math.max(initialData.length + 50, 100),
            columnCount: Math.max(headers.length, initialData[0]?.length || 0, 10) + 5,
          },
        },
      }
      headerCountRef.current = initialWorkbook ? 0 : (headers.length ? 1 : 0)
      const activeSheet = initialWorkbook ? Object.values(initialWorkbook.sheets || {})[0] as any : null
      colCountRef.current = Math.max(
        headers.length,
        initialData[0]?.length || 0,
        Number(activeSheet?.columnCount || 0),
        1,
      )
      univerAPI.createWorkbook(workbookData as any)

      univerRef.current = univerAPI

      // 单元格编辑后回调（含表头的完整数据）
      try {
        univerAPI.addEvent((univerAPI as any).Event.CellEdited, () => {
          if (onChangeRef.current && univerRef.current) {
            const data = readSheetValues(univerRef.current, 500, colCountRef.current)
            onChangeRef.current(data)
          }
        })
      } catch {
        /* 事件注册失败不影响基础编辑能力 */
      }

      return () => {
        univerRef.current = null
        univerAPI.dispose()
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
      <div
        ref={containerRef}
        style={{ height, width: '100%', border: '1px solid #d9d9d9', borderRadius: 4, overflow: 'hidden' }}
      />
    )
  }
)

SpreadsheetEditor.displayName = 'SpreadsheetEditor'

export default SpreadsheetEditor
