import React, { useState } from 'react';
import { Tabs, Card, Typography } from 'antd';
import RedTagList from './RedTagList';
import DefectList from './DefectList';

const { Title } = Typography;

const QMSModule: React.FC = () => {
  const [factoryId] = useState('demo-factory');
  
  return (
    <div>
      <Title level={2}>Quality Management System (QMS)</Title>
      
      <Tabs defaultActiveKey="defects" items={[
        {
          key: 'defects',
          label: 'Defects (不良品)',
          children: <DefectList factoryId={factoryId} />
        },
        {
          key: 'red-tags',
          label: 'Red Tags (质量红单)',
          children: <RedTagList factoryId={factoryId} />
        }
      ]} />
    </div>
  );
};

export default QMSModule;
