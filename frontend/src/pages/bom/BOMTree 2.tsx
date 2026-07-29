import React from 'react';
import { Tree } from 'antd';
import { FolderOutlined, FileOutlined } from '@ant-design/icons';

interface BOMNode {
  key: string;
  title: string;
  part_number: string;
  quantity: string;
  level: number;
  children?: BOMNode[];
}

interface Props {
  data: BOMNode[];
}

const BOMTree: React.FC<Props> = ({ data }) => {

  const treeData = data?.map((item) => ({
    key: item.key || item.part_number,
    title: (
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <span style={{ marginRight: 8 }}>{item.part_number}</span>
        <span style={{ color: '#888', fontSize: 12 }}>{item.quantity} / 层 {item.level}</span>
      </div>
    ),
    children: item.children ? treeData(item.children) : undefined,
  }));

  const renderTreeNode = (node: any) => (
    <Tree.Node key={node.key} {...node}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        {node.title}
      </div>
      {node.children && node.children.length > 0 && (
        <Tree.List>
          {node.children.map(renderTreeNode)}
        </Tree.List>
      )}
    </Tree.Node>
  );

  return (
    <Tree
      treeData={treeData || []}
      defaultExpandAll
      showIcon
      fieldNames={{ title: 'title', children: 'children', key: 'key' }}
      icon={() => <FolderOutlined />}
      style={{ maxHeight: 600, overflow: 'auto' }}
    />
  );
};

export default BOMTree;