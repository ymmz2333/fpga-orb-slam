"""PC-only synthetic geometry/rejection tests; never a real camera acceptance."""
from pathlib import Path
import csv,importlib.util,json,tempfile,unittest,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('usb_calibration',ROOT/'tools/calibrate_usb_camera.py');cal=importlib.util.module_from_spec(spec);spec.loader.exec_module(cal)
cv,np=cal.vision()
META=dict(source_width=1280,source_height=720,crop_x=160,crop_y=0,output_width=960,output_height=720,resized=False)

class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix=np.array([[740.,0.,470.],[0.,752.,352.],[0.,0.,1.]])
        cls.dist=np.array([-.06,.015,.001,-.001,.0015])
        board=np.zeros((54,3),np.float32);board[:,:2]=np.mgrid[0:9,0:6].T.reshape(-1,2)*25.
        rng=np.random.default_rng(83151);cls.objects=[];cls.pixels=[]
        for _ in range(2000):
            rotation=rng.uniform([-.6,-.6,-.4],[.6,.6,.4]);center=rng.uniform([-290.,-210.,440.],[240.,170.,820.]);r=cv.Rodrigues(rotation)[0]
            translation=center-r@np.mean(board,axis=0);image=cv.projectPoints(board,rotation,translation,cls.matrix,cls.dist)[0].astype(np.float32)
            if np.any(image[:,:,0]<8) or np.any(image[:,:,0]>951) or np.any(image[:,:,1]<8) or np.any(image[:,:,1]>711):continue
            cls.objects.append(board.copy());cls.pixels.append(image)
            if len(cls.objects)==30:break
        assert len(cls.objects)==30

    def test_known_geometry_and_crop_translation(self):
        values,report=cal.fit_observations(self.objects,self.pixels,META)
        self.assertEqual(report['status'],'PASS_CHECKERBOARD_FIT');self.assertLess(report['rms_pixels'],.001)
        self.assertLess(abs(values[2]-740),.1);self.assertLess(abs(values[3]-752),.1)
        self.assertLess(abs(values[4]-(470+160)),.1);self.assertLess(abs(values[5]-352),.1)
        self.assertLess(np.max(np.abs(np.array(values[6:])-self.dist)),.01)
        # Crop offsets affect principal point only, including1280x800 vertical crop.
        taller=dict(META,source_height=800,crop_y=40)
        restored=cal.source_values(self.matrix,self.dist,taller)
        self.assertEqual(restored[:2],[1280,800]);self.assertEqual(restored[4:6],[630.,392.])
        np.testing.assert_array_equal(restored[6:],self.dist)

    def test_refuse_insufficient_or_duplicate_views(self):
        with self.assertRaises(cal.Rejected):cal.fit_observations(self.objects[:14],self.pixels[:14],META)
        with self.assertRaises(cal.Rejected):cal.fit_observations([self.objects[0]]*20,[self.pixels[0]]*20,META)

    def test_refuse_nan_and_invalid_crop(self):
        corrupt=[p.copy() for p in self.pixels];corrupt[0][0,0,0]=np.nan
        with self.assertRaises(cal.Rejected):cal.fit_observations(self.objects,corrupt,META)
        for update in [dict(resized=True),dict(crop_x=0),dict(output_width=1280),dict(source_width=1920)]:
            with self.assertRaises(cal.Rejected):cal.crop_geometry(dict(META,**update))

    def test_refuse_bad_reprojection(self):
        noisy=[p.copy() for p in self.pixels];rng=np.random.default_rng(271)
        for p in noisy:p+=rng.normal(0,4,p.shape).astype(np.float32)
        with self.assertRaises(cal.Rejected):cal.fit_observations(self.objects,noisy,META)

    def test_bounded_view_quality_filter_retains_original_gates(self):
        points=[p.copy() for p in self.pixels];rng=np.random.default_rng(831)
        points[7]+=rng.normal(0,4,points[7].shape).astype(np.float32)
        before=[p.copy() for p in points]
        values,report,audit=cal.fit_with_view_rejection(self.objects,points,META,(9,6))
        self.assertEqual(report['usable_views'],29);self.assertEqual(report['status'],'PASS_CHECKERBOARD_FIT')
        self.assertEqual([v['observation_index'] for v in audit['excluded']],[7]);self.assertLess(report['rms_pixels'],.001)
        self.assertLess(abs(values[2]-740),.1)
        for a,b in zip(points,before):np.testing.assert_array_equal(a,b)
        # Over the fixed exclusion cap, all noisy, and insufficient views fail.
        for count in [4,30]:
            damaged=[p.copy() for p in self.pixels]
            for i in range(count):damaged[i]+=rng.normal(0,4,damaged[i].shape).astype(np.float32)
            with self.assertRaises(cal.Rejected):cal.fit_with_view_rejection(self.objects,damaged,META,(9,6))
        with self.assertRaises(cal.Rejected):cal.fit_with_view_rejection(self.objects[:14],points[:14],META,(9,6))

    def test_board_geometry_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.svg';cal.make_board(path);root=ET.fromstring(path.read_text())
            self.assertEqual(root.attrib['width'],'280mm');self.assertEqual(root.attrib['height'],'205mm')
            self.assertEqual(len(root.findall('{http://www.w3.org/2000/svg}rect')),36)
            self.assertEqual(json.loads(path.with_suffix('.json').read_text())['inner_corners'],[9,6])
            with self.assertRaises(RuntimeError):cal.make_board(path)

    def test_blank_capture_rejected_without_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            capture=Path(directory)/'capture';images=capture/'calibration-frames';images.mkdir(parents=True)
            (capture/'camera.json').write_text(json.dumps(META));data=b'P5\n960 720\n255\n'+bytes([255])*(960*720)
            with (images/'index.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['file','frame_index','timestamp_ns','width','height'])
                for i in range(15):
                    name=f'shot_{i}_frame_{i}.pgm';(images/name).write_bytes(data);writer.writerow([name,i,1+i*33333333,960,720])
            output=Path(directory)/'rejected';report=cal.calibrate(capture,output,25)
            self.assertEqual(report['status'],'REJECTED');self.assertFalse((output/'camera_source.csv').exists());self.assertTrue((output/'calibration_report.json').is_file())

    def test_q12_25_1p5_known_geometry(self):
        board=np.array([[c*1.5,r*1.5,0] for r in range(8) for c in range(11)],np.float32)
        rng=np.random.default_rng(20261024);objects=[];pixels=[]
        for _ in range(4000):
            rv=rng.uniform([-.65,-.65,-.4],[.65,.65,.4]);center=rng.uniform([-18.,-13.,24.],[16.,11.,52.])
            translation=center-cv.Rodrigues(rv)[0]@np.mean(board,axis=0)
            image=cv.projectPoints(board,rv,translation,self.matrix,self.dist)[0].astype(np.float32)
            if np.any(image[:,:,0]<8) or np.any(image[:,:,0]>951) or np.any(image[:,:,1]<8) or np.any(image[:,:,1]>711):continue
            objects.append(board.copy());pixels.append(image)
            if len(objects)==30:break
        self.assertEqual(len(objects),30)
        values,report=cal.fit_observations(objects,pixels,META,(11,8))
        self.assertEqual(report['inner_corners'],[11,8]);self.assertLess(report['rms_pixels'],.001)
        np.testing.assert_allclose(values[2:6],[740,752,630,352],atol=.1)
        np.testing.assert_allclose(values[6:],self.dist,atol=.01)
        with self.assertRaises(cal.Rejected):cal.fit_observations(objects,pixels,META,(12,9))

    def test_pattern_and_custom_board_bounds(self):
        for pattern in [(2,8),(11,0),(33,8),(32,32),(11.0,8),(True,8)]:
            with self.assertRaises(cal.Rejected):cal.checkerboard_pattern(pattern)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'q12.svg';cal.make_board(path,(11,8),1.5)
            meta=json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(meta['inner_corners'],[11,8]);self.assertEqual(meta['squares'],[12,9]);self.assertEqual(meta['square_mm'],1.5)
            svg=ET.fromstring(path.read_text())
            self.assertEqual(svg.attrib['width'],'48mm');self.assertEqual(svg.attrib['height'],'43.5mm')
            # Includes15mm print border, unlike the physical25x25mm commercial plate.
            self.assertEqual(len(svg.findall('{http://www.w3.org/2000/svg}rect')),55)

    def test_small_real_q12_in_clutter_preserves_original_coordinates(self):
        folder=ROOT/'tests/fixtures/calibration'
        path=folder/'q12_clutter.pgm';meta=json.loads((folder/'provenance.json').read_text())
        import hashlib
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),meta['sha256'])
        image=cv.imread(str(path),cv.IMREAD_GRAYSCALE);original=image.copy()
        corners,detection=cal.detect_checkerboard(image,(11,8))
        self.assertIsNotNone(corners);self.assertEqual(corners.shape,(88,1,2))
        self.assertEqual(detection['method'],'overlapping_original_pixel_tile')
        # Independently run the same detector on a tightly bounded original ROI
        # and restore its translation; never compare resampled corner pixels.
        found,reference=cv.findChessboardCornersSB(image[285:440,600:810],(11,8),flags=cv.CALIB_CB_NORMALIZE_IMAGE|cv.CALIB_CB_EXHAUSTIVE|cv.CALIB_CB_ACCURACY)
        self.assertTrue(found);reference[:,:,0]+=600;reference[:,:,1]+=285
        # This actual fixture has13..14px corner pitch, hence a4px radius.
        reference=cv.cornerSubPix(image,reference,(4,4),(-1,-1),(cv.TERM_CRITERIA_EPS|cv.TERM_CRITERIA_COUNT,100,.001))
        error=min(float(np.max(np.linalg.norm(corners-reference,axis=2))),float(np.max(np.linalg.norm(corners-reference[::-1],axis=2))))
        self.assertLess(error,.3);np.testing.assert_array_equal(image,original)
        for value in [image[:719],image.astype(np.float32)]:
            with self.assertRaises(cal.Rejected):cal.detect_checkerboard(value,(11,8))

    def test_detector_known_original_pixel_corners(self):
        image=np.full((720,960),220,np.uint8)
        for row in range(9):
            for column in range(12):
                image[220+28*row:220+28*(row+1),190+28*column:190+28*(column+1)]=20 if (row+column)%2==0 else 230
        corners,meta=cal.detect_checkerboard(image,(11,8));self.assertIsNotNone(corners)
        expected=np.asarray([[[190+28*c-.5,220+28*r-.5]] for r in range(1,9) for c in range(1,12)],np.float32)
        error=min(float(np.max(np.linalg.norm(corners-expected,axis=2))),float(np.max(np.linalg.norm(corners-expected[::-1],axis=2))))
        self.assertLess(error,.1);self.assertEqual(meta['refinement'],'original_full_image_subpixel')

    def test_classic_complete_grid_fallback_on_real_small_board(self):
        import hashlib
        folder=ROOT/'tests/fixtures/calibration';path=folder/'q12_classic.pgm'
        provenance=json.loads((folder/'classic_provenance.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),provenance['sha256'])
        image=cv.imread(str(path),cv.IMREAD_GRAYSCALE);corners,meta=cal.detect_checkerboard(image,(11,8))
        self.assertIsNotNone(corners);self.assertEqual(meta['algorithm'],'classic');self.assertEqual(corners.shape,(88,1,2))
        found,reference=cv.findChessboardCorners(image[180:540,240:720],(11,8),flags=cv.CALIB_CB_ADAPTIVE_THRESH|cv.CALIB_CB_NORMALIZE_IMAGE)
        self.assertTrue(found);reference[:,:,0]+=240;reference[:,:,1]+=180
        radius=meta['refinement_radius']
        reference=cv.cornerSubPix(image,reference,(radius,radius),(-1,-1),(cv.TERM_CRITERIA_EPS|cv.TERM_CRITERIA_COUNT,100,.001))
        np.testing.assert_allclose(corners,reference,atol=.001)

if __name__=='__main__':unittest.main(verbosity=2)
