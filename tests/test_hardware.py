"""Casos de estimación; no requieren GPU ni descargan modelos."""
import unittest
from hardware import GIB, recommend, vulkan_devices, quantization

class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.files=[{'file':f'model-{q}.gguf','size':n*GIB} for q,n in [('IQ2_M',5),('Q4_K_M',9),('Q6_K',13),('Q8_0',17)]]
    def test_discrete_vendors(self):
        for vendor in ('NVIDIA','AMD','Intel'):
            h={'available':30*GIB,'gpus':[{'vendor':vendor,'dedicated':True,'free':16*GIB}]}
            i,_=recommend(self.files,h,8192)
            self.assertEqual(i,1)
    def test_shared_not_added(self):
        h={'available':10*GIB,'gpus':[{'dedicated':False,'free':100*GIB}]}
        i,_=recommend(self.files,h,8192)
        self.assertEqual(i,0)
    def test_context_changes_budget(self):
        h={'available':16*GIB,'gpus':[]}
        self.assertEqual(recommend(self.files,h,8192)[0],1)
        self.assertIsNone(recommend(self.files,h,65536)[0])
    def test_quality_and_missing_data(self):
        h={'available':30*GIB,'gpus':[]}
        self.assertEqual(recommend(self.files,h,8192,2)[0],3)
        self.assertIsNone(recommend(self.files,{},8192)[0])
        self.assertIsNone(recommend([{'file':'unknown.gguf','size':1}],h,8192)[0])
    def test_vulkan_classification(self):
        text='GPU0:\n vendorID = 0x1002\n deviceID = 0x1234\n deviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n deviceName = AMD test\nGPU1:\n vendorID = 0x8086\n deviceID = 0x5678\n deviceType = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n deviceName = Intel test\n'
        d=vulkan_devices(text)
        self.assertEqual(len(d),2)
        self.assertIn('DISCRETE',d[(0x1002,0x1234)]['deviceType'])
        self.assertIn('INTEGRATED',d[(0x8086,0x5678)]['deviceType'])
    def test_quantization(self):
        self.assertEqual(quantization('foo-UD-IQ3_XXS.gguf'),3)
        self.assertEqual(quantization('foo-BF16.gguf'),16)
if __name__=='__main__': unittest.main()
