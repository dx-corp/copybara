/*
 * Copyright (C) 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.google.copybara.credentials;

import static com.google.common.truth.Truth.assertThat;

import com.beust.jcommander.JCommander;
import com.google.common.collect.ImmutableList;
import java.nio.file.Path;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

@RunWith(JUnit4.class)
public class CredentialOptionsTest {

  @Test
  public void credentialFileCanBeSuppliedFromTheCommandLine() {
    CredentialOptions options = new CredentialOptions();
    JCommander parser = new JCommander(ImmutableList.of(options));

    parser.parse("--credential-file", "/tmp/copybara-credentials.toml");

    assertThat(options.credentialFile.toString())
        .isEqualTo(Path.of("/tmp/copybara-credentials.toml").toString());
  }
}
