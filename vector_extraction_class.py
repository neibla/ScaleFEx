import data_query
import yaml,os,pickle
import parallelize_computation
import pandas as pd
import numpy as np
import scipy as sp
from datetime import datetime
import Load_preprocess_images.image_preprocessing_functions
import Quality_control_HCI.compute_global_values
import Embeddings_extraction_from_image.batch_compute_embeddings
import ScaleFEx_from_crop.compute_ScaleFEx
import cv2


class Screen_Compute: #come up with a better name
    """
    Class representing the computation of screen data.

    Methods:
        __init__(yaml_path='parameters.yaml'): 
            Initializes the Screen_Compute object with parameters from a YAML file.
    """
    def __init__(self, yaml_path='parameters.yaml'):
        """
        Initializes the Screen_Compute object with parameters from a YAML file.

        Args:
            yaml_path (str): Path to the YAML file containing parameters. Default is 'parameters.yaml'.
        """

        # Read the yaml file
        with open(yaml_path, 'rb') as f:
            self.parameters = yaml.load(f.read(), Loader=yaml.CLoader)
        f.close()

        # Determine the type of computation to be used
        if self.parameters['AWS']['use_AWS'] in['no','N','NO','n','Nope']:
            print('Local computation')
            self.computation='local'

        elif self.parameters['AWS']['use_AWS'] in ['yes','Y','YES','yes','y']:
            print(' AWS computation')   
            self.computation='AWS'

        else:
            print(self.parameters['AWS']['use_AWS'], ' is not an accepted character. Please specify Yes or No')

        # Import the data retrieval function
        self.data_retrieve = import_module(self.parameters[self.computation]['query_function'])

        # Print the experiment folder
        print("retrieving files from ", (self.parameters['location_parameters']['exp_folder']))

        # Get the files
        files = self.data_retrieve.query_data(self.parameters['location_parameters']['exp_folder'])

        # Perform Flat Field Correction (FFC)
        if self.parameters['FFC'] is True:
            if not os.path.exists(self.parameters['location_parameters']['saving_folder']+self.parameters['location_parameters']['experiment_name']+'_FFC.p'):
                print('Flat Field correction image not found in ' + self.parameters['location_parameters']['saving_folder'],
                    ' Generating FFC now')
                self.flat_field_correction={}

                self.flat_field_correction = self.data_retrieve.flat_field_correction_on_data(files,
                                                                                                self.parameters['type_specific']['channel'],
                                                                                                n_images=20)

                pickle.dump(self.flat_field_correction,
                            open(self.parameters['location_parameters']['saving_folder'] +
                                self.parameters['location_parameters']['experiment_name']+'_FFC.p', "wb"))

            else:
                print('Flat Field correction image found in ' + self.parameters['location_parameters']['saving_folder'],
                    ' Loding FFC')
                self.flat_field_correction = pickle.load(open(self.parameters['location_parameters']['saving_folder'] +
                            self.parameters['location_parameters']['experiment_name']+'_FFC.p', "rb"))
        else:
            for channel in self.parameters['type_specific']['channel']:
                self.flat_field_correction[channel]=1

        # Loop over plates and start computation
        for plate in self.parameters['location_parameters']['plates']:
            self.start_computation(plate, files)

### Start computation
            
    def start_computation(self,plate,files):
        #TB fixed
        
        # self.plate=plate
        task_files=files.loc[files.plate==plate]
        wells, task_fields = self.data_retrieve.make_well_and_field_list(task_files)
        if not os.path.exists(self.parameters['location_parameters']['saving_folder']+self.parameters['vector_type']):
            os.makedirs(self.parameters['location_parameters']['saving_folder']+self.parameters['vector_type'])

        csv_file = self.parameters['location_parameters']['saving_folder']+self.parameters['vector_type']+'/'+self.parameters['location_parameters']['experiment_name']+'_'+self.parameters['vector_type']+'.csv'
        if self.parameters['QC']==True:
            csv_fileQC = self.parameters['location_parameters']['saving_folder']+'QC_analysis/'+self.parameters['location_parameters']['experiment_name']+'_'+str(plate)+'QC.csv'
            if not os.path.exists(self.parameters['location_parameters']['saving_folder']+'QC_analysis'):
                os.makedirs(self.parameters['location_parameters']['saving_folder']+'QC_analysis')

        wells=self.data_retrieve.check_if_file_exists(csv_file,wells,task_fields[-1])

        if wells[0] == 'Over':
            print('plate ', plate, 'is done')
            return
            
        def compute_vector(well):
            ''' Function that imports the images and extracts the location of cells'''

            
            print(well, plate, datetime.now())
            for site in task_fields:
    
                print(site, well, plate, datetime.now())
                np_images, original_images = Load_preprocess_images.image_preprocessing_functions.load_and_preprocess(task_files,
                                    self.parameters['type_specific']['channel'],well,site,self.parameters['type_specific']['zstack'],self.data_retrieve,
                                    self.parameters['type_specific']['img_size'],self.flat_field_correction,
                                    self.parameters['downsampling'],return_original=self.parameters['QC'])
                try:
                    print(original_images.shape)
                except NameError:
                    print('Images corrupted')

                if np_images is not None:
                    if self.parameters['segmentation']['csv_coordinates']=='':
                        center_of_mass=self.segment_crop_images(original_images[0])
                        if self.parameters['type_specific']['compute_live_cells'] is False:
                            live_cells=len(center_of_mass)
                        else:
                            print('to be implemented')
                    else:
                        locations=pd.read_csv(self.parameters['segmentation']['csv_coordinates'],index_col=0)
                        locations['plate']=locations['plate'].astype(str)
                        locations=locations.loc[(locations.well==well)&(locations.site==site)&(locations.plate==plate)]
                        center_of_mass=np.asarray(locations[['coordX','coordY']])
                        if self.parameters['type_specific']['compute_live_cells'] is False:
                            live_cells=len(center_of_mass)
                        
                        
                    #print(center_of_mass)

                    if self.parameters['QC']==True:
                        indQC=0

                        QC_vector,indQC = Quality_control_HCI.compute_global_values.calculateQC(len(center_of_mass),live_cells,
                                            self.parameters['location_parameters']['experiment_name'],original_images,well,plate,site,self.parameters['type_specific']['channel'],
                                            indQC,self.parameters['type_specific']['neurite_tracing'])
                        if not os.path.exists(csv_fileQC):
                            QC_vector.to_csv(csv_fileQC,header=True)
                        else:
                            QC_vector.to_csv(csv_fileQC,mode='a',header=False)

                    if self.parameters['tile_computation'] is True:
                        ind=0
                        vector=pd.DataFrame(np.asarray([plate,well,site]).reshape(1,3),columns=['plate','well','site'],index=[ind])
                        vector=pd.concat([vector,Embeddings_extraction_from_image.batch_compute_embeddings.Compute_embeddings(np_images,ind,self.parameters['type_specific']['channel'],
                                                                                            self.parameters["device"],weights=self.parameters['weights_location']).embeddings],axis=1)
                        if not os.path.exists(csv_file[:-4]+'Tile.csv'):
                            vector.to_csv(csv_file[:-4]+'Tile.csv',header=True)
                        else:
                            vector.to_csv(csv_file[:-4]+'Tile.csv',mode='a',header=False)
                    n=0
                    for x,y in center_of_mass:
                        crop=np_images[:,int(x-self.parameters['type_specific']['ROI']):int(x+self.parameters['type_specific']['ROI']),
                                           int(y-self.parameters['type_specific']['ROI']):int(y+self.parameters['type_specific']['ROI']),:]
                        # if ((x-self.parameters['type_specific']['ROI']<0) or (x-self.parameters['type_specific']['ROI']>self.parameters['location_parameters']['image_size'][0]) or
                        #     (y-self.parameters['type_specific']['ROI']<0) or (y-self.parameters['type_specific']['ROI']>self.parameters['location_parameters']['image_size'][1])):
                        if crop.shape != (len(self.parameters['type_specific']['channel']),self.parameters['type_specific']['ROI']*2,self.parameters['type_specific']['ROI']*2,1):
                            print(crop.shape, "cell on the border")
                            continue
                        else:
                            ind=0
                            vector=pd.DataFrame(np.asarray([plate,well,site,x,y,n]).reshape(1,6),columns=['plate','well','site','coordX','coordY','cell_id'],index=[ind])

                            n+=1
                            if self.parameters['location_parameters']['coordinates_csv']=='':
                             
                                ccDistance=[]
                                for cord in center_of_mass:  
                                    ccDistance.append(sp.spatial.distance.pdist([[x,y], cord]))   
                                    ccDistance.sort()     
                                vector['distance']=ccDistance[1]   

                            
                            print(crop.shape)

                            if 'mbed' in self.parameters['vector_type']:

                                vector=pd.concat([vector,Embeddings_extraction_from_image.batch_compute_embeddings.Compute_embeddings(crop,0,self.parameters['type_specific']['channel'],
                                                                                                self.parameters["device"],weights=self.parameters['weights_location']).embeddings],axis=1)
                                
                                if not os.path.exists(csv_file):
                                    vector.to_csv(csv_file,header=True)
                                else:
                                    vector.to_csv(csv_file,mode='a',header=False)
                            
                            elif ('cale' in self.parameters['vector_type']) or ('FEx' in self.parameters['vector_type']) or ('fex' in self.parameters['vector_type']):
                                
                                vector=pd.concat([vector,ScaleFEx_from_crop.compute_ScaleFEx.ScaleFEx(crop, channel=self.parameters['type_specific']['channel'],
                                                    mito_ch=self.parameters['type_specific']['Mito_channel'], rna_ch=self.parameters['type_specific']['RNA_channel'],
                                                    neuritis_ch=self.parameters['type_specific']['neurite_tracing'],downsampling=self.parameters['downsampling'], 
                                                    visualization=False, roi=int(self.parameters['type_specific']['ROI'])).single_cell_vector.loc[1,0]],axis=1)
                                print(vector)
                                if not os.path.exists(csv_file):
                                    vector.to_csv(csv_file,header=True)
                                else:
                                    vector.to_csv(csv_file,mode='a',header=False)
                            
                            else:
                                print(' Not a valid vector type entry')


        if self.computation=='local':
            if self.parameters['local']['parallel'] is True:
                function = compute_vector
                parallelize_computation.parallelize_local(wells,function)
            else:
                for well in wells:
                    compute_vector(well)
        elif self.computation=='AWS':
            print('Gab to finish :) ')

    def segment_crop_images(self,img_nuc):

        # extraction of the location of the cells
    
        nls=import_module(self.parameters['segmentation']['segmenting_function'])
        center_of_mass = nls.retrieve_coordinates(nls.compute_DNA_mask(img_nuc),
                    cell_size_min=self.parameters['segmentation']['min_cell_size']*self.parameters['downsampling'],
                    cell_size_max=self.parameters['segmentation']['max_cell_size']/self.parameters['downsampling'])
        try:
            center_of_mass
        except NameError:
            center_of_mass = []
            print('No Cells detected')
        

        return center_of_mass
                        


def import_module(module_name):
    try:
        module = __import__(module_name)
        return module
    except ImportError:
        print(f"Module '{module_name}' not found.")
        return None
    
if __name__ == "__main__":
	Screen_Compute()
