import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { SeoService } from '../seo.service';

const DATASET_JSONLD_ID = 'jsonld-dataset';

@Component({
  selector: 'app-about',
  imports: [RouterLink, MatButtonModule, MatIconModule],
  templateUrl: './about.html',
  styleUrl: './about.scss',
})
export class AboutComponent implements OnInit, OnDestroy {
  private seo = inject(SeoService);

  ngOnInit(): void {
    this.seo.updateMetadata({
      title: 'Over OpenGrondWaterKaart',
      description:
        'Achtergrond, doel en databronnen van OpenGrondWaterKaart: een open kaart met grondwaterstanden in Nederland, gebaseerd op BRO- en PDOK-data.',
      path: '/about',
    });

    this.seo.setJsonLd(DATASET_JSONLD_ID, {
      '@context': 'https://schema.org',
      '@type': 'Dataset',
      name: 'Grondwaterstanden Nederland',
      description:
        'Grondwaterstanden van meetputten in Nederland, afgeleid van de BRO Grondwatermonitoring en PDOK.',
      url: 'https://opengrondwaterkaart.nl/about',
      inLanguage: 'nl',
      license: 'https://github.com/bartromgens/opengrondwaterkaart/blob/master/LICENSE.md',
      creator: {
        '@type': 'Organization',
        name: 'TNO / Basisregistratie Ondergrond (BRO)',
      },
    });
  }

  ngOnDestroy(): void {
    this.seo.removeJsonLd(DATASET_JSONLD_ID);
  }
}
